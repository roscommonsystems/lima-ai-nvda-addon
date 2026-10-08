# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: global plugin.

import threading
import time

import globalPluginHandler
import ui
import gui
import queueHandler
import speech
from speech.priorities import Spri
from speech.commands import LangChangeCommand
import addonHandler
import braille
import api
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
from . import announcements

addonHandler.initTranslation()


# Maps a selected reply language to the NVDA/synth locale, so a non-English reply is spoken
# with that language's voice (needs a synth that supports it, e.g. eSpeak NG has Filipino).
# English is absent: the reply is already in the default voice's language.
_SPEECH_LOCALES = {"tl": "fil", "vi": "vi"}


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
		self._last_narration_time = 0.0
		self._web_narrator = webnarration.WebNarrator(
			capture,
			vision,
			settings.get_id_token,
			self._speak_queued,
			get_language=settings.get_language,
			interval=settings.get_web_narration_interval(),
			change_threshold=settings.get_web_narration_threshold(),
			on_error=self._narration_error,
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

	def _status_text(self, message):
		return announcements.status_text(message, settings.get_language(), _)

	def _narration_error(self, code):
		queueHandler.queueFunction(queueHandler.eventQueue, self._announce_status, self._error_message(code), Spri.NEXT)

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
			"rate_limited": self._status_text("The AI service is temporarily busy. Please try again later."),
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
		if self._describing:
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
			self._announce_status(self._error_message("signed_out"))
			return
		if self._describing:
			self._announce_status(self._error_message("busy"))
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
			png = capture.capture_element_png(
				(location.left, location.top, location.width, location.height)
			)
			if png is None:
				raise ValueError
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
		message = self._error_message("api_error")
		locale = "vi" if settings.get_language() == "vi" else None
		try:
			message = vision.describe_element(png, context, id_token, language=settings.get_language())
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
				queueHandler.queueFunction(queueHandler.eventQueue, self._announce_status, self._status_text("Web page update:"), Spri.NEXT, False)
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
			self._announce_status(self._error_message("signed_out"))
			return
		active = self._web_narrator.toggle()
		# Translators: spoken when web narration is turned on or off.
		self._announce_status(self._status_text("Web narration on") if active else self._status_text("Web narration off"))
