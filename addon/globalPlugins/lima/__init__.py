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
from scriptHandler import script

from . import capture
from . import vision
from . import settings
from . import webnarration

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Top-level LIMA AI add-on plugin. Holds the add-on's global commands."""

	#: Shown as the command category in NVDA's Input Gestures dialog.
	scriptCategory = _("LIMA AI")

	def __init__(self):
		super().__init__()
		settings.initialize()
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settings.LimaSettingsPanel)
		self._describing = False
		self._web_narrator = webnarration.WebNarrator(
			capture,
			vision,
			settings.get_api_key,
			settings.get_model,
			self._speak_queued,
			interval=settings.get_web_narration_interval(),
			change_threshold=settings.get_web_narration_threshold(),
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
			# Translators: spoken when no API key has been configured.
			"no_key": _("Set your OpenRouter API key in LIMA AI settings."),
			# Translators: spoken when a description is already in progress.
			"busy": _("Still describing the previous screen, please wait."),
			# Translators: spoken when the screen could not be captured.
			"capture": _("Could not capture the screen."),
			# Translators: spoken when the AI service cannot be reached.
			"network": _("Could not reach the AI service. Check your connection and try again."),
			# Translators: spoken when the AI service returns an error.
			"api_error": _("The AI service returned an error. Check your API key in LIMA AI settings."),
			# Translators: spoken when the AI returns no usable description.
			"empty": _("No description was returned. Try again."),
		}
		return messages.get(code, messages["api_error"])

	@script(
		# Translators: Description of the command that confirms the add-on loaded.
		description=_("Announces that the LIMA AI add-on is running."),
		gesture="kb:NVDA+shift+l",
	)
	def script_announceRunning(self, gesture):
		# Translators: Spoken message confirming the add-on is active.
		ui.message(_("LIMA AI add-on is running"))

	@script(
		# Translators: Description of the describe-screen command.
		description=_("Describe what is currently on the screen."),
		gesture="kb:NVDA+shift+d",
	)
	def script_describeScreen(self, gesture):
		api_key = settings.get_api_key()
		if not api_key:
			ui.message(self._error_message("no_key"))
			return
		if self._describing:
			ui.message(self._error_message("busy"))
			return
		self._describing = True
		if not settings.is_welcome_shown():
			# Translators: one-time message pointing users to the full desktop product.
			ui.message(_("Welcome to LIMA AI for NVDA. For the full hands-free experience, try the LIMA desktop app."))
			settings.mark_welcome_shown()
		# Translators: spoken immediately when a description request starts.
		ui.message(_("Describing screen."))
		try:
			png = capture.capture_screen_png()
		except Exception:
			self._describing = False
			ui.message(self._error_message("capture"))
			return
		model = settings.get_model()
		thread = threading.Thread(
			target=self._run_describe, args=(png, api_key, model), daemon=True
		)
		thread.start()

	def _run_describe(self, png, api_key, model):
		message = self._error_message("api_error")
		try:
			message = vision.describe_image(png, api_key, model)
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
		gesture="kb:NVDA+shift+w",
	)
	def script_toggleWebNarration(self, gesture):
		if not settings.get_api_key():
			ui.message(self._error_message("no_key"))
			return
		active = self._web_narrator.toggle()
		# Translators: spoken when web narration is turned on or off.
		ui.message(_("Web narration on") if active else _("Web narration off"))
