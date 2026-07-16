# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: configuration spec and settings panel.

import threading

import config
import wx
import gui
import ui
from gui.settingsDialogs import SettingsPanel

import addonHandler

from . import auth
from . import firebase_config

addonHandler.initTranslation()

CONFIG_SECTION = "lima"
DEFAULT_MODEL = "openai/gpt-4o-mini"

CONFIG_SPEC = {
	"apiKey": 'string(default="")',
	"model": 'string(default="%s")' % DEFAULT_MODEL,
	"welcomeShown": "boolean(default=false)",
	"refreshToken": 'string(default="")',
	"userUid": 'string(default="")',
	"userEmail": 'string(default="")',
	"userDisplayName": 'string(default="")',
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


def get_refresh_token():
	return config.conf[CONFIG_SECTION]["refreshToken"]


def is_signed_in():
	return bool(config.conf[CONFIG_SECTION]["refreshToken"])


def get_user_email():
	return config.conf[CONFIG_SECTION]["userEmail"]


def get_user_display_name():
	return config.conf[CONFIG_SECTION]["userDisplayName"]


def save_session(session):
	c = config.conf[CONFIG_SECTION]
	c["refreshToken"] = session.get("refreshToken", "")
	c["userUid"] = session.get("uid", "")
	c["userEmail"] = session.get("email", "")
	c["userDisplayName"] = session.get("displayName", "")


def clear_session():
	c = config.conf[CONFIG_SECTION]
	c["refreshToken"] = ""
	c["userUid"] = ""
	c["userEmail"] = ""
	c["userDisplayName"] = ""


class LimaSettingsPanel(SettingsPanel):
	# Translators: Title of the LIMA AI category in NVDA's settings dialog.
	title = _("LIMA AI")

	# User-facing text for each sign-in failure code (kept out of auth.py so it
	# stays NVDA-free).
	_SIGN_IN_ERRORS = {
		# Translators: shown when sign-in is not configured in this build.
		"config": _("Google sign-in is not set up in this build of LIMA AI."),
		# Translators: shown when the sign-in service cannot be reached.
		"network": _("Could not reach the sign-in service. Check your connection and try again."),
		# Translators: shown when the user closes the browser or denies access.
		"cancelled": _("Sign-in was cancelled."),
		# Translators: shown when the browser sign-in is not completed in time.
		"timeout": _("Sign-in timed out. Please try again."),
		# Translators: shown when sign-in fails for any other reason.
		"auth_error": _("Sign-in failed. Please try again."),
	}

	def makeSettings(self, settingsSizer):
		helper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		# Translators: Label for the OpenRouter API key field.
		self.apiKeyEdit = helper.addLabeledControl(_("OpenRouter API &key:"), wx.TextCtrl)
		self.apiKeyEdit.SetValue(get_api_key())
		# Translators: Label for the model identifier field.
		self.modelEdit = helper.addLabeledControl(_("&Model:"), wx.TextCtrl)
		self.modelEdit.SetValue(get_model())

		# Translators: label of the Google account group in LIMA AI settings.
		accountSizer = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Google account")), wx.VERTICAL)
		accountBox = accountSizer.GetStaticBox()
		accountHelper = gui.guiHelper.BoxSizerHelper(self, sizer=accountSizer)
		helper.addItem(accountHelper)
		self.accountStatus = accountHelper.addItem(wx.StaticText(accountBox, label=self._account_status()))
		self.signInButton = accountHelper.addItem(wx.Button(accountBox, label=self._button_label()))
		self.signInButton.Bind(wx.EVT_BUTTON, self.onSignInOut)

	def _account_status(self):
		if is_signed_in():
			# Translators: shown when a user is signed in; %s is their email or name.
			return _("Signed in as %s") % (get_user_email() or get_user_display_name())
		# Translators: shown when no user is signed in.
		return _("Not signed in.")

	def _button_label(self):
		if is_signed_in():
			# Translators: button that signs the current user out.
			return _("Sign &out")
		# Translators: button that starts Google sign-in.
		return _("Sign in with &Google")

	def _refresh_account_ui(self):
		self.accountStatus.SetLabel(self._account_status())
		self.signInButton.SetLabel(self._button_label())

	def onSignInOut(self, evt):
		if is_signed_in():
			clear_session()
			self._refresh_account_ui()
			return
		if not firebase_config.is_configured():
			gui.messageBox(self._SIGN_IN_ERRORS["config"], _("LIMA AI"), wx.OK | wx.ICON_ERROR)
			return
		self.signInButton.Disable()
		# Translators: shown while the browser sign-in is in progress.
		self.accountStatus.SetLabel(_("Opening your browser to sign in…"))
		thread = threading.Thread(
			target=self._run_sign_in, args=(firebase_config.get_config(),), daemon=True
		)
		thread.start()

	def _run_sign_in(self, cfg):
		# Runs off the GUI thread; the browser flow blocks. Marshal results back
		# with wx.CallAfter so all UI work happens on the main thread.
		try:
			session = auth.run_sign_in(cfg)
		except auth.AuthError as e:
			wx.CallAfter(self._sign_in_failed, e.code)
		except Exception:
			wx.CallAfter(self._sign_in_failed, "auth_error")
		else:
			wx.CallAfter(self._sign_in_succeeded, session)

	def _sign_in_succeeded(self, session):
		save_session(session)
		self.signInButton.Enable()
		self._refresh_account_ui()
		# Announce success by speech/braille instead of a modal dialog: the user
		# stays in the settings panel and nothing needs dismissing.
		# Translators: confirmation spoken after a successful sign-in; %s is the account.
		ui.message(_("Signed in as %s.") % (session.get("email") or session.get("displayName") or _("your Google account")))

	def _sign_in_failed(self, code):
		self.signInButton.Enable()
		self._refresh_account_ui()
		gui.messageBox(self._SIGN_IN_ERRORS.get(code, self._SIGN_IN_ERRORS["auth_error"]), _("LIMA AI"), wx.OK | wx.ICON_ERROR)

	def onSave(self):
		config.conf[CONFIG_SECTION]["apiKey"] = self.apiKeyEdit.GetValue().strip()
		model = self.modelEdit.GetValue().strip()
		config.conf[CONFIG_SECTION]["model"] = model or DEFAULT_MODEL
