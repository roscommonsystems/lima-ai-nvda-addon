# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: global plugin.

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

addonHandler.initTranslation()

log = logging.getLogger(__name__)


# Maps a selected reply language to the NVDA/synth locale, so a non-English reply is spoken
# with that language's voice (needs a synth that supports it, e.g. eSpeak NG has Filipino).
# English is absent: the reply is already in the default voice's language.
_SPEECH_LOCALES = {"tl": "fil"}

# Earcons for the click command, so a blind user hears what is happening before the words: a
# short tone when the search starts, a higher tone when the click succeeds, and a lower, longer
# tone when it fails (nothing found, no match, or an error). Frequency in hertz, duration in ms.
_CLICK_START_TONE = (440, 80)
_CLICK_OK_TONE = (660, 100)
_CLICK_FAIL_TONE = (300, 180)
# A soft, short tick repeated while the AI search runs, so the user knows LIMA is still working.
_CLICK_WAIT_TONE = (350, 40)
_CLICK_WAIT_INTERVAL_MS = 800


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
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settings.LimaSettingsPanel)
		self._describing = False
		# True only while the click-by-description prompt is on screen, so a second NVDA+Alt+C
		# press cannot stack a second dialog on top of the first.
		self._click_prompt_open = False
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
					"and to toggle web narration press NVDA+Alt+W. "
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

	# Spoken messages for each failure code (kept here so vision.py stays NVDA-free).
	def _error_message(self, code):
		messages = {
			# Translators: spoken when the user is not signed in.
			"signed_out": _("Sign in with Google in LIMA AI settings to use this feature."),
			# Translators: spoken when another LIMA request is already running.
			"busy": _("LIMA is busy, please wait."),
			# Translators: spoken when the screen could not be captured.
			"capture": _("Could not capture the screen or element."),
			# Translators: spoken when the AI service cannot be reached.
			"network": _("Could not reach the AI service. Check your connection and try again."),
			# Translators: spoken when the AI service returns an error.
			"api_error": _("The AI service is temporarily unavailable. Please try again in a moment."),
			# Translators: spoken when the AI returns no usable answer.
			"empty": _("The AI service gave no usable answer. Please try again."),
			# Translators: spoken when the focused element has no visible location to capture.
			"focus": _("The focused element has no visible location to capture. Move to a control and try again."),
			# Translators: spoken when the click could not be performed.
			"click_failed": _("The click could not be performed. Please try again."),
		}
		return messages.get(code, messages["api_error"])

	# Default gestures use the NVDA+Alt layer (D: describe screen, E: describe focused element, W:
	# web narration), which NVDA core leaves free apart from the braille auto-scroll keys
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
		ui.message(_("LIMA AI add-on is running"))

	@script(
		# Translators: Description of the describe-screen command.
		description=_("Describe what is currently on the screen."),
		gesture="kb:NVDA+alt+d",
	)
	def script_describeScreen(self, gesture):
		id_token = settings.get_id_token()
		if not id_token:
			ui.message(self._error_message("signed_out"))
			return
		if self._describing or self._searching:
			ui.message(self._error_message("busy"))
			return
		self._describing = True
		# Translators: spoken immediately when a description request starts.
		ui.message(_("Describing screen."))
		try:
			png = capture.capture_screen_png()
		except Exception:
			self._describing = False
			ui.message(self._error_message("capture"))
			return
		thread = threading.Thread(
			target=self._run_describe, args=(png, id_token), daemon=True
		)
		thread.start()

	def _run_describe(self, png, id_token):
		message = self._error_message("api_error")
		locale = None
		try:
			message = vision.describe_image(png, id_token, language=settings.get_language())
			# A successful description is in the selected reply language; the error messages
			# above stay in the interface language, so only tag the language on success.
			locale = _SPEECH_LOCALES.get(settings.get_language())
		except vision.VisionError as e:
			message = self._error_message(e.code)
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
			ui.message(self._error_message("signed_out"))
			return
		if self._describing or self._searching:
			ui.message(self._error_message("busy"))
			return
		obj = self._element_target()
		if obj is None:
			ui.message(self._error_message("focus"))
			return
		context = self._element_context(obj)
		self._describing = True
		# Translators: Spoken immediately when an element-description request starts.
		ui.message(_("Describing element."))
		try:
			location = getattr(obj, "location", None)
			if not location:
				raise ValueError
			png = capture.capture_element_png(
				(location.left, location.top, location.width, location.height)
			)
			if png is None:
				raise ValueError
		except ValueError:
				self._describing = False
				ui.message(self._error_message("focus"))
				return
		except Exception:
				self._describing = False
				ui.message(self._error_message("capture"))
				return
		thread = threading.Thread(
			target=self._run_describe_element, args=(png, context, id_token), daemon=True
		)
		thread.start()

	def _run_describe_element(self, png, context, id_token):
		message = self._error_message("api_error")
		locale = None
		try:
			message = vision.describe_element(png, context, id_token, language=settings.get_language())
			# A successful description is in the selected reply language;the error messages
			# above stay in the interface language, so only tag the language on success.
			locale = _SPEECH_LOCALES.get(settings.get_language())
		except vision.VisionError as e:
			message = self._error_message(e.code)
		except Exception:
			pass  # keep the default api_error message
		finally:
			self._describing = False
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
				queueHandler.queueFunction(queueHandler.eventQueue, speech.speakMessage, _("Web page update:"), Spri.NEXT)
			elif mode == "sound":
				queueHandler.queueFunction(queueHandler.eventQueue, tones.beep, 660, 80)
		locale = _SPEECH_LOCALES.get(settings.get_language())
		queueHandler.queueFunction(queueHandler.eventQueue, self._speak_localized, text, locale, Spri.NEXT, False)

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
			ui.message(self._error_message("signed_out"))
			return
		active = self._web_narrator.toggle()
		# Translators: spoken when web narration is turned on or off.
		ui.message(_("Web narration on") if active else _("Web narration off"))

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
			ui.message(_("Search cancelled."))
			return
		if self._click_prompt_open:
			return  # the prompt is already open; ignore the repeat press rather than stacking a dialog
		id_token = settings.get_id_token()
		if not id_token:
			ui.message(self._error_message("signed_out"))
			return
		if self._describing:
			ui.message(self._error_message("busy"))
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
		try:
			screenshot = capture.capture_screen_png()
		except Exception:
			self._searching = False
			ui.message(self._error_message("capture"))
			return
		tones.beep(*_CLICK_START_TONE)
		# Translators: spoken while LIMA locates the target; {desc} is the user's own words.
		ui.message(_("Finding {desc}.").format(desc=description))
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
			error = e.code
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
			failure = _("I could not find anything to click here.")
		elif error is not None:
			failure = self._error_message(error)
		elif index is None:
			# Translators: spoken when nothing on screen matched; {desc} is the user's description.
			failure = _("I could not find {desc}.").format(desc=description)
		else:
			failure = None
		if failure is not None:
			tones.beep(*_CLICK_FAIL_TONE)
			ui.message(failure)
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
			ui.message(self._error_message("click_failed"))
			return
		tones.beep(*_CLICK_OK_TONE)
		if action == "double":
			# Translators: spoken after a double-click; {name} is the element name.
			ui.message(_("Double-clicked {name}.").format(name=element.name))
		elif action == "right":
			# Translators: spoken after a right-click; {name} is the element name.
			ui.message(_("Right-clicked {name}.").format(name=element.name))
		else:
			# Translators: spoken after a single click; {name} is the element name.
			ui.message(_("Clicked {name}.").format(name=element.name))
