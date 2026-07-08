# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: configuration spec and settings panel.

import config
import wx
import gui
from gui.settingsDialogs import SettingsPanel

import addonHandler

addonHandler.initTranslation()

CONFIG_SECTION = "lima"
DEFAULT_MODEL = "openai/gpt-4o-mini"

CONFIG_SPEC = {
	"apiKey": 'string(default="")',
	"model": 'string(default="%s")' % DEFAULT_MODEL,
	"welcomeShown": "boolean(default=false)",
}


def initialize():
	"""Register the add-on's configuration spec. Call once on plugin init."""
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


def get_api_key():
	return config.conf[CONFIG_SECTION]["apiKey"]


def get_model():
	return config.conf[CONFIG_SECTION]["model"]


def is_welcome_shown():
	return config.conf[CONFIG_SECTION]["welcomeShown"]


def mark_welcome_shown():
	config.conf[CONFIG_SECTION]["welcomeShown"] = True


class LimaSettingsPanel(SettingsPanel):
	# Translators: Title of the LIMA AI category in NVDA's settings dialog.
	title = _("LIMA AI")

	def makeSettings(self, settingsSizer):
		helper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		# Translators: Label for the OpenRouter API key field.
		self.apiKeyEdit = helper.addLabeledControl(_("OpenRouter API &key:"), wx.TextCtrl)
		self.apiKeyEdit.SetValue(get_api_key())
		# Translators: Label for the model identifier field.
		self.modelEdit = helper.addLabeledControl(_("&Model:"), wx.TextCtrl)
		self.modelEdit.SetValue(get_model())

	def onSave(self):
		config.conf[CONFIG_SECTION]["apiKey"] = self.apiKeyEdit.GetValue().strip()
		model = self.modelEdit.GetValue().strip()
		config.conf[CONFIG_SECTION]["model"] = model or DEFAULT_MODEL
