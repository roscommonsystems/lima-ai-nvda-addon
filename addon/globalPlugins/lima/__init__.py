# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: global plugin.

import threading

import globalPluginHandler
import ui
import gui
import queueHandler
import speech
from speech.priorities import Spri
import addonHandler
import core
from scriptHandler import script

from . import capture
from . import vision
from . import settings
from . import webnarration
from . import firebase_config

addonHandler.initTranslation()


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
		self._web_narrator = webnarration.WebNarrator(
			capture,
			vision,
			settings.get_id_token,
			self._speak_queued,
			interval=settings.get_web_narration_interval(),
			change_threshold=settings.get_web_narration_threshold(),
			# Translators: spoken before each dynamic web-narration update.
			narration_prefix=_("Web page update:") + " ",
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
			# Translators: spoken when a description is already in progress.
			"busy": _("Still describing the previous screen, please wait."),
			# Translators: spoken when the screen could not be captured.
			"capture": _("Could not capture the screen."),
			# Translators: spoken when the AI service cannot be reached.
			"network": _("Could not reach the AI service. Check your connection and try again."),
			# Translators: spoken when the AI service returns an error.
			"api_error": _("The AI service returned an error. Please try again."),
			# Translators: spoken when the AI returns no usable description.
			"empty": _("No description was returned. Try again."),
		}
		return messages.get(code, messages["api_error"])

	# Default gestures use the NVDA+Alt layer, which NVDA core leaves free apart from the
	# braille auto-scroll keys (J/K/L). We deliberately avoid NVDA+Shift+D and similar,
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
		if self._describing:
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
		try:
			message = vision.describe_image(png, id_token)
		except vision.VisionError as e:
			message = self._error_message(e.code)
		except Exception:
			pass  # keep the default api_error message
		finally:
			self._describing = False
		# NVDA speech must run on the main thread.
		queueHandler.queueFunction(queueHandler.eventQueue, ui.message, message)

	def _speak_queued(self, text):
		# Queued at NEXT priority so it never interrupts what NVDA is reading.
		queueHandler.queueFunction(queueHandler.eventQueue, speech.speakMessage, text, Spri.NEXT)

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
