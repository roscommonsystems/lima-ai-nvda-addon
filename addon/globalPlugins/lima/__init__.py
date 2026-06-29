# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: global plugin.

import globalPluginHandler
import ui
import addonHandler
from scriptHandler import script

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Top-level LIMA add-on plugin. Holds the add-on's global commands."""

	#: Shown as the command category in NVDA's Input Gestures dialog.
	scriptCategory = _("LIMA")

	@script(
		# Translators: Description of the command that confirms the add-on loaded.
		description=_("Announces that the LIMA add-on is running."),
		gesture="kb:NVDA+shift+l",
	)
	def script_announceRunning(self, gesture):
		# Translators: Spoken message confirming the add-on is active.
		ui.message(_("LIMA add-on is running"))
