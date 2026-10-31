# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: global plugin.

import io
import logging
import threading
import time

import globalPluginHandler
import ui
import gui
import wx
import queueHandler
import speech
from speech.priorities import Spri
from speech.commands import LangChangeCommand
import addonHandler
import braille
import api
import winUser
import textInfos
import config
import core
import tones
from scriptHandler import script

from . import capture
from . import vision
from . import settings
from . import webnarration
from . import firebase_config
from . import uielements
from . import mouseclick
from . import announcements
from . import usage

addonHandler.initTranslation()

log = logging.getLogger(__name__)


# Maps a selected reply language to the NVDA/synth locale, so a non-English reply is spoken
# with that language's voice (needs a synth that supports it, e.g. eSpeak NG has Filipino).
# English is absent: the reply is already in the default voice's language.
_SPEECH_LOCALES = {"tl": "fil", "vi": "vi"}

# Earcons for the click command, so a blind user hears what is happening before the words: a
# short tone when the search starts, a higher tone when the click succeeds, and a lower, longer
# tone when it fails (nothing found, no match, or an error). Frequency in hertz, duration in ms.
_CLICK_START_TONE = (440, 80)
_CLICK_OK_TONE = (660, 100)
_CLICK_FAIL_TONE = (300, 180)
# A soft, short tick repeated while the AI search runs, so the user knows LIMA is still working.
_CLICK_WAIT_TONE = (350, 40)
_CLICK_WAIT_INTERVAL_MS = 800

# How long after the Describe Element window opens to start reading the description aloud, so the
# reading follows NVDA's own announcement of the window instead of being cancelled by it.
_DESCRIBE_READ_DELAY_MS = 500


class _ClickTargetDialog(wx.Dialog):
	"""Accessible prompt for the click target, built the way NVDA's own dialogs are.

	A labelled single-line edit that NVDA narrates like any edit field (typed characters, and
	Ctrl+Arrow word review), plus standard OK and Cancel buttons NVDA names on Tab. Escape and
	the title-bar close button cancel.
	"""

	def __init__(self, parent):
		# Translators: title of the click-by-description dialog.
		super().__init__(parent, title=_("LIMA AI"))
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		contents = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		# Translators: label of the field for describing what to click.
		self.inputCtrl = contents.addLabeledControl(_("Describe what you want to click:"), wx.TextCtrl)
		mainSizer.Add(contents.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		if buttons is not None:
			mainSizer.Add(buttons, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.EXPAND | wx.ALL)
		self.SetSizerAndFit(mainSizer)
		self.CentreOnScreen()
		# Start on the edit field so the user can type straight away; without this wx would put the
		# initial focus on the default OK button. NVDA announces the dialog and this field when the
		# dialog opens, which works because the script shows it via wx.CallAfter rather than from
		# inside its keyboard hook.
		self.inputCtrl.SetFocus()

	def get_value(self):
		return self.inputCtrl.GetValue().strip()


class _DescribeResultDialog(wx.Dialog):
	"""Accessible results window for Describe Element, laid out like JAWS Picture Smart Results.

	The captured element is shown beside its description, which sits in a read-only multiline
	field the user can reread with the arrow keys and NVDA's review commands (line, word,
	character). Below, a question field asks LIMA a follow-up about the element or the area
	around it, and More details asks for a fuller description; each question and answer is added
	to the description field. Copy puts that text on the clipboard. The Close button has the
	Cancel id, so Escape closes the window too.
	"""

	def __init__(self, parent, description, image, context, ask):
		# Translators: title of the Describe Element results window.
		super().__init__(parent, title=_("LIMA AI element description"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		# The capture this window describes. Follow-up questions are asked about the same image and
		# accessibility text: the element lost focus to this window, so it can't be recaptured.
		self.image = image
		self.context = context
		# Called with this window and the question when the user asks a follow-up; returns whether
		# the question was sent.
		self._ask = ask
		gap = self.FromDIP(8)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		# The captured element on the left, its description on the right taking any extra room when
		# the window is resized.
		resultSizer = wx.BoxSizer(wx.HORIZONTAL)
		picture = wx.Image(io.BytesIO(image))
		width, height = capture.scaled_size(picture.GetWidth(), picture.GetHeight(), self.FromDIP(240))
		thumbnail = picture.Scale(width, height, wx.IMAGE_QUALITY_HIGH)
		resultSizer.Add(wx.StaticBitmap(self, bitmap=wx.Bitmap(thumbnail)), flag=wx.RIGHT, border=2 * gap)
		descriptionSizer = wx.BoxSizer(wx.VERTICAL)
		# Translators: label of the read-only field holding the element description.
		descriptionSizer.Add(wx.StaticText(self, label=_("Description:")))
		self.resultCtrl = wx.TextCtrl(self, value=description, style=wx.TE_MULTILINE | wx.TE_READONLY, size=self.FromDIP(wx.Size(520, 260)))
		descriptionSizer.Add(self.resultCtrl, proportion=1, flag=wx.EXPAND | wx.TOP, border=gap // 2)
		resultSizer.Add(descriptionSizer, proportion=1, flag=wx.EXPAND)
		mainSizer.Add(resultSizer, proportion=1, flag=wx.EXPAND | wx.ALL, border=gui.guiHelper.BORDER_FOR_DIALOGS)
		questionSizer = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: label of the field for asking a follow-up question about the element.
		questionSizer.Add(wx.StaticText(self, label=_("Ask a follow-up question:")), flag=wx.ALIGN_CENTER_VERTICAL)
		self.questionCtrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
		self.questionCtrl.Bind(wx.EVT_TEXT_ENTER, self._on_ask)
		questionSizer.Add(self.questionCtrl, proportion=1, flag=wx.LEFT | wx.RIGHT, border=gap)
		# Translators: button that asks LIMA the follow-up question.
		askButton = wx.Button(self, label=_("&Ask"))
		askButton.Bind(wx.EVT_BUTTON, self._on_ask)
		questionSizer.Add(askButton)
		mainSizer.Add(questionSizer, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)
		buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: button that asks LIMA for a fuller description of the element.
		moreButton = wx.Button(self, label=_("&More details"))
		moreButton.Bind(wx.EVT_BUTTON, self._on_more_details)
		buttonSizer.Add(moreButton)
		buttonSizer.AddStretchSpacer()
		# Translators: button that copies the description to the clipboard.
		copyButton = wx.Button(self, label=_("&Copy"))
		copyButton.Bind(wx.EVT_BUTTON, self._on_copy)
		buttonSizer.Add(copyButton)
		# Translators: button that closes the results window.
		buttonSizer.Add(wx.Button(self, id=wx.ID_CANCEL, label=_("Cl&ose")), flag=wx.LEFT, border=gap)
		mainSizer.Add(buttonSizer, flag=wx.EXPAND | wx.ALL, border=gui.guiHelper.BORDER_FOR_DIALOGS)
		self.SetSizerAndFit(mainSizer)
		self.CentreOnScreen()
		# Start in the description so the arrow keys reread it straight away.
		self.resultCtrl.SetFocus()

	def _on_copy(self, evt):
		# api.copyToClip announces "Copied to clipboard" itself.
		api.copyToClip(self.resultCtrl.GetValue(), notify=True)

	def _on_ask(self, evt):
		question = self.questionCtrl.GetValue().strip()
		# Cleared only once the question is sent, so one LIMA refuses (busy, or signed out) can be
		# sent again without retyping it.
		if question and self._ask(self, question):
			self.questionCtrl.Clear()

	def _on_more_details(self, evt):
		# Translators: the follow-up question the More details button asks LIMA.
		self._ask(self, _("Describe it in more detail."))

	def add_answer(self, question, answer):
		"""Add a follow-up question and its answer under the description, with the caret at the
		question, so moving back to the description field reads the new exchange first."""
		if not self:
			return  # the window was closed while the answer was on its way
		self.resultCtrl.AppendText("\n\n")
		start = self.resultCtrl.GetLastPosition()
		# Translators: a follow-up question and LIMA's answer, as added to the results window.
		self.resultCtrl.AppendText(_("Question: {question}\nAnswer: {answer}").format(question=question, answer=answer))
		self.resultCtrl.SetInsertionPoint(start)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Top-level LIMA AI add-on plugin. Holds the add-on's global commands."""

	#: Shown as the command category in NVDA's Input Gestures dialog.
	scriptCategory = _("LIMA AI")

	def __init__(self):
		super().__init__()
		settings.initialize()
		# Point the vision client at the configured LIMA backend proxy (all AI calls go
		# through it so the OpenRouter key never reaches the client).
		vision.ENDPOINT_URL = firebase_config.LIMA_BACKEND_URL + "/v1/chat/completions"
		# Credit usage comes from the same backend, which holds the key and reads it from
		# OpenRouter; only the percentage comes back.
		usage.ENDPOINT_URL = firebase_config.LIMA_BACKEND_URL + "/usage"
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settings.LimaSettingsPanel)
		self._describing = False
		# True while NVDA+Alt+U is waiting on the backend, so repeat presses do not stack requests.
		self._checking_usage = False
		# True only while the click-by-description prompt is on screen, so a second NVDA+Alt+C
		# press cannot stack a second dialog on top of the first.
		self._click_prompt_open = False
		# True from the moment an element description arrives until its results window closes, so a
		# second NVDA+Alt+E press cannot stack a second window on top of the first.
		self._result_window_open = False
		# True while a click search (enumerate + AI) is running: drives the working tick and lets a
		# second NVDA+Alt+C cancel it.
		self._searching = False
		self._last_narration_time = 0.0
		self._web_narrator = webnarration.WebNarrator(
			capture,
			vision,
			settings.get_id_token,
			self._speak_queued,
			get_language=settings.get_language,
			interval=settings.get_web_narration_interval(),
			change_threshold=settings.get_web_narration_threshold(),
			on_error=self._narration_failed,
		)
		# On first run, announce the add-on and its default shortcuts so users learn how to
		# use it without hunting through Input Gestures. Deferred a few seconds so it does not
		# collide with NVDA's own startup speech, and shown only once (welcomeShown flag).
		if not settings.is_welcome_shown():
			settings.mark_welcome_shown()
			core.callLater(
				4000,
				ui.message,
				# Translators: one-time spoken introduction naming the add-on's shortcuts.
				_(
					"Welcome to LIMA AI. To describe your screen press NVDA+Alt+D, "
					"to describe the focused element press NVDA+Alt+E, "
					"to click something by describing it press NVDA+Alt+C, "
					"to toggle web narration press NVDA+Alt+W, "
					"and to hear your credit usage press NVDA+Alt+U. "
					"You can change these shortcuts in NVDA's Input Gestures."
				),
			)

	def terminate(self):
		self._web_narrator.stop()
		try:
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(settings.LimaSettingsPanel)
		except ValueError:
			pass
		super().terminate()

	def _status_text(self, message):
		return announcements.status_text(message, settings.get_language(), _)

	def _announce_status(self, text, priority=Spri.NORMAL, show_in_braille=True):
		if settings.get_language() == "vi":
			self._speak_localized(text, "vi", priority, show_in_braille)
		elif show_in_braille:
			ui.message(text)
		else:
			speech.speakMessage(text, priority)

	# Spoken messages for each failure code (kept here so vision.py stays NVDA-free).
	def _error_message(self, code):
		messages = {
			# Translators: spoken when the user is not signed in.
			"signed_out": self._status_text("Sign in with Google in LIMA AI settings to use this feature."),
			# Translators: spoken when a description is already in progress.
			"busy": self._status_text("Still describing, please wait."),
			# Translators: spoken when the screen could not be captured.
			"capture": self._status_text("Could not capture the screen or element."),
			# Translators: spoken when the AI service cannot be reached.
			"network": self._status_text("Could not reach the AI service. Check your connection and try again."),
			# Translators: spoken when the AI service returns an error.
			"api_error": self._status_text("The AI service returned an error. Please try again."),
			# Translators: spoken when the AI returns no usable description.
			"empty": self._status_text("No description was returned. Try again."),
			# Translators: spoken when the focused element has no visible location to capture.
			"focus": self._status_text("The focused element has no visible location to capture. Move to a control and try again."),
			# Translators: spoken when the click could not be performed.
			"click_failed": self._status_text("The click could not be performed. Please try again."),
			# Translators: spoken when the AI service refuses a request because too many were sent in a short time.
			"rate_limited": self._status_text("Too many requests. Please wait a moment and try again."),
		}
		return messages.get(code, messages["api_error"])

	def _vision_error_message(self, error):
		"""The spoken message for a VisionError. A spent credit says when it comes back,
		using the reset date the backend sent with its 402."""
		if error.code == "credit_exhausted":
			return usage.limit_message(
				usage.reset_policy(error.resets),
				usage.reset_date(error.resets_at),
				self._status_text,
				settings.get_language(),
			)
		return self._error_message(error.code)

	def _announce_translated(self, text):
		"""Announce a line that is translated into every LIMA language (the credit lines).

		Unlike _announce_status, Tagalog gets the Filipino voice too: these lines exist in
		Tagalog, while the add-on's other command messages are still English for Tagalog users.
		"""
		locale = _SPEECH_LOCALES.get(settings.get_language())
		if locale:
			self._speak_localized(text, locale, Spri.NORMAL, True)
		else:
			ui.message(text)

	# Default gestures use the NVDA+Alt layer (D: describe screen, E: describe focused element, W:
	# web narration, C: click by description, U: credit usage), which NVDA core leaves free apart
	# from the braille auto-scroll keys
	# (J/K/L). We deliberately avoid NVDA+Shift+D and similar,
	# because those already map to NVDA commands (NVDA+Shift+D is the audio-ducking toggle).
	# The minor "announce running" health check ships unbound. Every command has a
	# description and scriptCategory, so all of them appear in NVDA's Input Gestures dialog
	# under "LIMA AI" for the user to reassign or add shortcuts of their own.
	@script(
		# Translators: Description of the command that confirms the add-on loaded.
		description=_("Announces that the LIMA AI add-on is running."),
	)
	def script_announceRunning(self, gesture):
		# Translators: Spoken message confirming the add-on is active.
		self._announce_status(self._status_text("LIMA AI add-on is running"))

	@script(
		# Translators: Description of the describe-screen command.
		description=_("Describe what is currently on the screen."),
		gesture="kb:NVDA+alt+d",
	)
	def script_describeScreen(self, gesture):
		id_token = settings.get_id_token()
		if not id_token:
			self._announce_status(self._error_message("signed_out"))
			return
		if self._describing or self._searching:
			self._announce_status(self._error_message("busy"))
			return
		self._describing = True
		# Translators: spoken immediately when a description request starts.
		self._announce_status(self._status_text("Describing screen."))
		try:
			png = capture.capture_screen_png()
		except Exception:
			self._describing = False
			self._announce_status(self._error_message("capture"))
			return
		thread = threading.Thread(
			target=self._run_describe, args=(png, id_token), daemon=True
		)
		thread.start()

	def _run_describe(self, png, id_token):
		message = self._error_message("api_error")
		locale = "vi" if settings.get_language() == "vi" else None
		try:
			message = vision.describe_image(png, id_token, language=settings.get_language())
			locale = _SPEECH_LOCALES.get(settings.get_language())
		except vision.VisionError as e:
			message = self._vision_error_message(e)
			if e.code == "credit_exhausted":
				# Translated into every LIMA language, so it is spoken in that language's voice.
				locale = _SPEECH_LOCALES.get(settings.get_language())
		except Exception:
			pass  # keep the default api_error message
		finally:
			self._describing = False
		# NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, self._speak_localized, message, locale, Spri.NORMAL, True)

	@script(
		# Translators: Description of the command that describes the currently focused element.
		description=_("Describe the currently focused element."),
		gesture="kb:NVDA+alt+e",
	)
	def script_describeElement(self, gesture):
		id_token = settings.get_id_token()
		if not id_token:
			self._announce_status(self._error_message("signed_out"))
			return
		if self._describing or self._searching:
			self._announce_status(self._error_message("busy"))
			return
		if self._result_window_open:
			# Translators: spoken when NVDA+Alt+E is pressed while its results window is already open.
			self._announce_status(self._status_text("The element description is already open."))
			return
		obj = self._element_target()
		if obj is None:
			self._announce_status(self._error_message("focus"))
			return
		context = self._element_context(obj)
		self._describing = True
		# Translators: Spoken immediately when an element-description request starts.
		self._announce_status(self._status_text("Describing element."))
		try:
			location = getattr(obj, "location", None)
			if not location:
				raise ValueError
			rect = (location.left, location.top, location.width, location.height)
			png = capture.capture_element_png(rect)
			if png is None:
				raise ValueError
			# The image shows only the area around the element, so say where on the screen it is.
			context += "\nPosition on screen: " + capture.screen_position(rect)
		except ValueError:
				self._describing = False
				self._announce_status(self._error_message("focus"))
				return
		except Exception:
				self._describing = False
				self._announce_status(self._error_message("capture"))
				return
		thread = threading.Thread(
			target=self._run_describe_element, args=(png, context, id_token), daemon=True
		)
		thread.start()

	def _run_describe_element(self, png, context, id_token):
		description = None
		message = self._error_message("api_error")
		locale = "vi" if settings.get_language() == "vi" else None
		try:
			description = vision.describe_element(png, context, id_token, language=settings.get_language())
			locale = _SPEECH_LOCALES.get(settings.get_language())
		except vision.VisionError as e:
			message = self._vision_error_message(e)
			if e.code == "credit_exhausted":
				locale = _SPEECH_LOCALES.get(settings.get_language())
		except Exception:
			pass  # keep the default api_error message
		finally:
			if description:
				# Marked open before the busy flag clears, because the window only appears once the main
				# thread gets to it; an NVDA+Alt+E press in between then can't start a second one.
				self._result_window_open = True
			self._describing = False
		if description:
			# Shown in a window the user can reread and ask follow-ups in. Opened with wx.CallAfter,
			# not NVDA's queue: a modal window opened from NVDA's queue blocks NVDA's core, which then
			# stops reporting focus and speech for as long as the window is open.
			wx.CallAfter(self._show_element_result, description, png, context, locale)
			return
		# NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, self._speak_localized, message, locale, Spri.NORMAL, True)

	def _show_element_result(self, description, png, context, locale):
		gui.mainFrame.prePopup()
		window = _DescribeResultDialog(gui.mainFrame, description, png, context, self._ask_followup)
		# Read the whole description aloud once NVDA has announced the window, as JAWS Picture Smart
		# does; the field then lets the user reread it at their own pace.
		core.callLater(_DESCRIBE_READ_DELAY_MS, self._speak_localized, description, locale, Spri.NORMAL, True)
		try:
			window.ShowModal()
		finally:
			self._result_window_open = False
			window.Destroy()
			# Back in the app window, where focus returns to the element that was described.
			gui.mainFrame.postPopup()

	def _ask_followup(self, window, question):
		# Called by the results window when the user asks a follow-up question; returns whether it
		# was sent. The sign-in token is fetched now, not kept from the description, so a window
		# left open stays usable.
		id_token = settings.get_id_token()
		if not id_token:
			self._announce_status(self._error_message("signed_out"))
			return False
		if self._describing or self._searching:
			self._announce_status(self._error_message("busy"))
			return False
		self._describing = True
		# Translators: spoken while LIMA answers a follow-up question about the described element.
		self._announce_status(self._status_text("Asking LIMA."))
		thread = threading.Thread(target=self._run_followup, args=(window, question, id_token), daemon=True)
		thread.start()
		return True

	def _run_followup(self, window, question, id_token):
		answer = None
		message = self._error_message("api_error")
		locale = "vi" if settings.get_language() == "vi" else None
		try:
			answer = vision.answer_element_question(window.image, window.context, question, id_token, language=settings.get_language())
			message = answer
			locale = _SPEECH_LOCALES.get(settings.get_language())
		except vision.VisionError as e:
			message = self._vision_error_message(e)
			if e.code == "credit_exhausted":
				locale = _SPEECH_LOCALES.get(settings.get_language())
		except Exception:
			pass  # keep the default api_error message
		finally:
			self._describing = False
		if answer:
			wx.CallAfter(window.add_answer, question, answer)
		# NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, self._speak_localized, message, locale, Spri.NORMAL, True)

	def _element_target(self):
		"""Best-effort: the real focused (possibly virtual) element, drilling into
		browse-mode documents so the actual focused element is captured, not the whole
		document."""
		try:
			focus = api.getFocusObject()
		except Exception:
			return None
		if not focus:
			return None
		obj = focus
		try:
			ti = focus.treeInterceptor
		except Exception:
			ti = None
		if ti is not None:
			try:
				cand = ti.makeTextInfo(textInfos.POSITION_CARET).focusableNVDAObjectAtStart
			except Exception:
				cand = None
			if cand is not None and self._has_visible_location(cand):
				obj = cand
		return obj

	def _has_visible_location(self, obj):
		location = getattr(obj, "location", None)
		return bool(location and getattr(location, "width", 0) > 0 and getattr(location, "height", 0) > 0)

	def _element_context(self, obj):
		"""Compact accessibility-tree description of the focused element, for extra context
		alongside the image crop: name, role, states, value, keyboard shortcut, description,
		and up to 3 ancestors (e.g. the dialog or toolbar containing the element)."""
		parts = []
		if obj is None:
			return ""
		def add(label, value):
			if isinstance(value, str):
				value = self._clip(value)
			if value:
				parts.append(f"{label}: {value}")
		role = getattr(obj, "role", None)
		if role is not None:
			role = getattr(role, "displayString", None) or getattr(role, "displayName", None) or role
		if role:
			add("Role", str(role))
		add("Name", getattr(obj, "name", None))
		value = getattr(obj, "value", None)
		name = getattr(obj, "name", None)
		if value is not None and (not isinstance(value, str) or value != name):
			add("Value", value)
		add("Keyboard shortcut", getattr(obj, "keyboardShortcut", None))
		add("Description", getattr(obj, "description", None))
		states = getattr(obj, "states", None)
		if states:
			labels = []
			for state in sorted(states, key=str):
				labels.append(getattr(state, "displayString", None) or getattr(state, "displayName", None) or str(state))
			if labels:
				add("States", ", ".join(labels))
		context = []
		parent = getattr(obj, "parent", None)
		for _ in range(3):
			if parent is None:
				break
			pname = getattr(parent, "name", None)
			prole = getattr(parent, "role", None)
			if prole is not None:
				prole = getattr(prole, "displayString", None) or getattr(prole, "displayName", None) or prole
			label = str(prole if prole else "object")
			if pname:
				label += f" '{self._clip(pname)}'"
			context.append(label)
			parent = getattr(parent, "parent", None)
		if context:
			add("Inside", ", ".join(context))
		return "\n".join(parts)

	def _clip(self, value, limit=120):
		"""Truncate long accessible strings so the prompt stays compact."""
		value = value.strip()
		if len(value) > limit:
			return value[: limit - 1] + "..."
		return value

	def _speak_queued(self, text):
		# Runs on the web-narration timer thread. Everything is queued at NEXT priority so it
		# never interrupts what NVDA is reading. The pre-announcement (a spoken phrase, a short
		# beep, or nothing) comes from settings and is suppressed during a rapid run of updates
		# (a playing video): it is only given when the previous update was more than two
		# intervals ago, a genuinely new change rather than a continuing stream. The description
		# itself is always spoken.
		section = config.conf[settings.CONFIG_SECTION]
		now = time.time()
		fresh = (now - self._last_narration_time) > (2 * section["webNarrationIntervalSeconds"])
		self._last_narration_time = now
		if fresh:
			mode = section["webNarrationPreAnnounce"]
			if mode == "speech":
				# Translators: spoken before each web-narration update.
				queueHandler.queueFunction(queueHandler.eventQueue, self._announce_status, self._status_text("Web page update:"), Spri.NEXT, False)
			elif mode == "sound":
				queueHandler.queueFunction(queueHandler.eventQueue, tones.beep, 660, 80)
		locale = _SPEECH_LOCALES.get(settings.get_language())
		queueHandler.queueFunction(queueHandler.eventQueue, self._speak_localized, text, locale, Spri.NEXT, False)

	def _narration_failed(self, code, error, stopped):
		# Runs on the web-narration timer thread; NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, self._report_narration_failure, code, error, stopped)

	def _report_narration_failure(self, code, error, stopped):
		"""Tell the user why narration failed. The narrator reports each failure once, not
		every interval, and stops by itself when the credit is used up or the user signed out."""
		if code == "credit_exhausted" and error is not None:
			self._announce_translated(self._vision_error_message(error))
		else:
			self._announce_status(self._error_message(code))
		if stopped:
			# Translators: spoken when web narration is turned on or off.
			self._announce_status(self._status_text("Web narration off"))

	def _speak_localized(self, text, locale, priority, show_in_braille):
		"""Speak `text` at `priority` on the main thread. When `locale` is set, switch the voice
		to that language so a non-English reply is pronounced by a synth that supports it; show it
		in braille when asked (the on-demand description does, continuous narration does not)."""
		if locale:
			speech.speak([LangChangeCommand(locale), text], priority=priority)
		else:
			speech.speakMessage(text, priority)
		if show_in_braille:
			braille.handler.message(text)

	@script(
		# Translators: Description of the command that toggles web narration.
		description=_("Toggle dynamic web narration on or off."),
		gesture="kb:NVDA+alt+w",
	)
	def script_toggleWebNarration(self, gesture):
		# Stopping is always allowed; only starting requires being signed in.
		if not self._web_narrator.is_active and not settings.get_id_token():
			self._announce_status(self._error_message("signed_out"))
			return
		active = self._web_narrator.toggle()
		# Translators: spoken when web narration is turned on or off.
		self._announce_status(self._status_text("Web narration on") if active else self._status_text("Web narration off"))

	# Credit usage. Speaks the same line as the LIMA AI settings panel and as LIMA desktop's
	# Subscription dialog: "Credits used this month: 34% — resets in 4 days". The backend
	# works out the percentage from the user's OpenRouter key and sends only that back.
	@script(
		# Translators: Description of the command that announces credit usage.
		description=_("Announces how much of your LIMA credit you have used."),
		gesture="kb:NVDA+alt+u",
	)
	def script_announceCreditUsage(self, gesture):
		id_token = settings.get_id_token()
		if not id_token:
			self._announce_status(self._error_message("signed_out"))
			return
		if self._checking_usage:
			return  # the answer to the previous press is on its way
		self._checking_usage = True
		# Translators: spoken while LIMA asks the backend for the user's credit usage.
		self._announce_translated(self._status_text("Checking credit usage."))
		thread = threading.Thread(target=self._run_credit_usage, args=(id_token,), daemon=True)
		thread.start()

	def _run_credit_usage(self, id_token):
		result = None
		try:
			result = usage.fetch_credit_usage(id_token)
		except Exception:
			log.exception("LIMA credit usage check failed")
		finally:
			self._checking_usage = False
		line = usage.usage_text(result, usage.today_utc(), self._status_text, settings.get_language())
		# NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, self._announce_translated, line)

	# Click by description. The user describes what to do in plain words ("open the Downloads
	# folder", "click the Send button", "right-click the file"); LIMA enumerates the on-screen
	# clickable elements from the accessibility tree, the vision model picks the matching element
	# and the action it needs (single, double, or right click), and LIMA performs it at the
	# element's center. The coordinates come from the accessibility tree, never from the model, so
	# a click can only ever land on a real listed control. Bound to NVDA+Alt+C (the same NVDA+Alt
	# layer LIMA already uses); reassignable in Input Gestures under LIMA AI.
	@script(
		# Translators: Description of the command that clicks a described element.
		description=_("Click an on-screen element you describe."),
		gesture="kb:NVDA+alt+c",
	)
	def script_clickElement(self, gesture):
		wx.CallAfter(self._click_by_description)

	def _click_by_description(self):
		"""Prompt for a target, then locate and click it. The script dispatches this with
		wx.CallAfter so it runs on a fresh turn of the GUI event loop rather than inside NVDA's
		keyboard hook: a modal dialog opened directly from a script blocks that hook, and NVDA
		then neither announces the dialog nor echoes what the user types into it.
		"""
		if self._searching:
			# A second press while a search is running cancels it.
			self._searching = False
			tones.beep(*_CLICK_FAIL_TONE)
			# Translators: spoken when the user cancels a click search in progress.
			self._announce_status(self._status_text("Search cancelled."))
			return
		if self._click_prompt_open:
			return  # the prompt is already open; ignore the repeat press rather than stacking a dialog
		id_token = settings.get_id_token()
		if not id_token:
			self._announce_status(self._error_message("signed_out"))
			return
		if self._describing:
			self._announce_status(self._error_message("busy"))
			return
		# Capture the top-level foreground window before our dialog takes focus, so enumeration and
		# the screenshot are of the user's window, not our dialog. The Win32 foreground window is
		# the whole app window, so its UIA subtree covers everything (menu bar included), unlike the
		# focused control, which on some apps is just the inner text area.
		foreground_hwnd = winUser.getForegroundWindow()
		# Ask what to click; Escape or Cancel aborts.
		self._click_prompt_open = True
		gui.mainFrame.prePopup()
		dialog = _ClickTargetDialog(gui.mainFrame)
		try:
			description = dialog.get_value() if dialog.ShowModal() == wx.ID_OK else ""
		finally:
			dialog.Destroy()
			gui.mainFrame.postPopup()
			self._click_prompt_open = False
		if not description:
			return
		self._searching = True
		# Closing the dialog makes NVDA announce the window regaining focus; spoken immediately,
		# the start signal below is cancelled by that announcement and the user misses it. Defer a
		# moment so the focus announcement passes first, then signal and begin the search.
		core.callLater(200, self._begin_search, foreground_hwnd, description, id_token)

	def _begin_search(self, foreground_hwnd, description, id_token):
		# Runs on the GUI thread a moment after the prompt closes. Capture the screen now (the
		# prompt is gone), signal that the search has started, and hand the slow work to a worker.
		if not self._searching:
			return  # cancelled during the 200ms deferral window
		try:
			screenshot = capture.capture_screen_png()
		except Exception:
			self._searching = False
			self._announce_status(self._error_message("capture"))
			return
		tones.beep(*_CLICK_START_TONE)
		# Translators: spoken while LIMA locates the target; {desc} is the user's own words.
		self._announce_status(self._status_text("Finding {desc}.").format(desc=description))
		core.callLater(_CLICK_WAIT_INTERVAL_MS, self._pulse_working)
		thread = threading.Thread(
			target=self._run_select,
			args=(foreground_hwnd, screenshot, description, id_token),
			daemon=True,
		)
		thread.start()

	def _pulse_working(self):
		# A soft repeating tick while the search runs, so the user knows LIMA is still working.
		# It reschedules itself until _finish_click (or a cancel) clears self._searching.
		if not self._searching:
			return
		tones.beep(*_CLICK_WAIT_TONE)
		core.callLater(_CLICK_WAIT_INTERVAL_MS, self._pulse_working)

	def _run_select(self, foreground_hwnd, screenshot, description, id_token):
		# Enumeration and the AI call both run here, off NVDA's GUI thread: a UIA walk returns the
		# full window only from a worker thread, and the network call must not block speech. Every
		# dialog, spoken message, and the click itself stays on the GUI thread via queueFunction.
		elements = []
		index = None
		action = "single"
		error = None
		try:
			elements, debug = uielements.enumerate_clickable(foreground_hwnd)
			log.debug("LIMA click enumeration: %s", debug)
			if not elements:
				error = "no_elements"
			else:
				reply = vision.select_element(
					screenshot, uielements.format_elements_for_prompt(elements), description, id_token,
				)
				index, action = vision.parse_selection(reply, len(elements))
		except vision.VisionError as e:
			# Kept whole rather than as e.code: a spent credit carries its reset date.
			error = e
		except Exception:
			log.exception("LIMA click selection failed")
			error = "api_error"
		queueHandler.queueFunction(
			queueHandler.eventQueue, self._finish_click, foreground_hwnd, elements, index, action, description, error
		)

	def _finish_click(self, foreground_hwnd, elements, index, action, description, error):
		if not self._searching:
			return  # the user cancelled the search while it was running; stay silent
		self._searching = False  # we are reporting now, so stop the working tick
		# Any failure gets the low "failed" earcon so the outcome is clear before the words.
		if error == "no_elements":
			# Translators: spoken when nothing clickable was found on screen.
			failure = self._status_text("I could not find anything to click here.")
		elif isinstance(error, vision.VisionError) and error.code == "credit_exhausted":
			tones.beep(*_CLICK_FAIL_TONE)
			self._announce_translated(self._vision_error_message(error))
			return
		elif isinstance(error, vision.VisionError):
			failure = self._error_message(error.code)
		elif error is not None:
			failure = self._error_message(error)
		elif index is None:
			# Translators: spoken when nothing on screen matched; {desc} is the user's description.
			failure = self._status_text("I could not find {desc}.").format(desc=description)
		else:
			failure = None
		if failure is not None:
			tones.beep(*_CLICK_FAIL_TONE)
			self._announce_status(failure)
			return
		# Perform the action the model chose from the user's wording (single, double, or right
		# click), the way the flagship's mouse-click tool does. The coordinates come from the
		# accessibility tree, so a wrong pick can still only land on a real listed control, and
		# NVDA announces the focus change the click causes, so the user still hears what happened.
		element = elements[index - 1]
		button = "right" if action == "right" else "left"
		double = action == "double"
		try:
			mouseclick.click_at(element.center, foreground_hwnd, button, double)
		except Exception:
			log.exception("LIMA click could not be performed")
			tones.beep(*_CLICK_FAIL_TONE)
			self._announce_status(self._error_message("click_failed"))
			return
		tones.beep(*_CLICK_OK_TONE)
		if action == "double":
			# Translators: spoken after a double-click; {name} is the element name.
			self._announce_status(self._status_text("Double-clicked {name}.").format(name=element.name))
		elif action == "right":
			# Translators: spoken after a right-click; {name} is the element name.
			self._announce_status(self._status_text("Right-clicked {name}.").format(name=element.name))
		else:
			# Translators: spoken after a single click; {name} is the element name.
			self._announce_status(self._status_text("Clicked {name}.").format(name=element.name))
