# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: configuration spec and settings panel.

import threading
import time

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

CONFIG_SPEC = {
	"welcomeShown": "boolean(default=false)",
	"webNarrationIntervalSeconds": "float(default=6.0)",
	"webNarrationChangeThreshold": "float(default=0.03)",
	"webNarrationPreAnnounce": 'string(default="speech")',
	"webNarrationPrefix": 'string(default="Web page update:")',
	"refreshToken": 'string(default="")',
	"userUid": 'string(default="")',
	"userEmail": 'string(default="")',
	"userDisplayName": 'string(default="")',
}


def initialize():
	"""Register the add-on's configuration spec. Call once on plugin init."""
	config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC


# --- Firebase ID token provider ----------------------------------------------
# AI calls are proxied through the LIMA backend and authenticated with the user's
# Firebase ID token. Tokens last ~1 hour, so cache one in memory and refresh it from
# the stored refresh token when it expires. Guarded by a lock because describe/narration
# calls run on background threads.

_token_lock = threading.Lock()
_cached_id_token = ""
_cached_expiry = 0.0


def get_id_token():
	"""Return a valid Firebase ID token, refreshing when expired. "" if signed out."""
	global _cached_id_token, _cached_expiry
	with _token_lock:
		if _cached_id_token and time.time() < _cached_expiry:
			return _cached_id_token
		refresh_token = get_refresh_token()
		if not refresh_token:
			return ""
		try:
			session = auth.restore_session(firebase_config.get_config(), refresh_token)
		except auth.AuthError:
			return ""
		_cached_id_token = session.get("idToken", "")
		_cached_expiry = session.get("expiresAt", 0.0)
		new_refresh = session.get("refreshToken", "")
		if new_refresh:
			config.conf[CONFIG_SECTION]["refreshToken"] = new_refresh
		return _cached_id_token


def _clear_token_cache():
	"""Drop the in-memory token so the next call re-refreshes (used on sign-out)."""
	global _cached_id_token, _cached_expiry
	with _token_lock:
		_cached_id_token = ""
		_cached_expiry = 0.0


def get_web_narration_interval():
	return config.conf[CONFIG_SECTION]["webNarrationIntervalSeconds"]


def get_web_narration_threshold():
	return config.conf[CONFIG_SECTION]["webNarrationChangeThreshold"]


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
	# Prime the token cache from the fresh sign-in so the first AI call needs no refresh.
	global _cached_id_token, _cached_expiry
	with _token_lock:
		_cached_id_token = session.get("idToken", "")
		_cached_expiry = session.get("expiresAt", 0.0)


def clear_session():
	c = config.conf[CONFIG_SECTION]
	c["refreshToken"] = ""
	c["userUid"] = ""
	c["userEmail"] = ""
	c["userDisplayName"] = ""
	_clear_token_cache()


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
		# The AI service is reached by signing in with Google — there is no API key to
		# enter. Calls are proxied through the LIMA backend using the Firebase token.

		# Translators: label of the Google account group in LIMA AI settings.
		accountSizer = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Google account")), wx.VERTICAL)
		accountBox = accountSizer.GetStaticBox()
		accountHelper = gui.guiHelper.BoxSizerHelper(self, sizer=accountSizer)
		helper.addItem(accountHelper)
		self.accountStatus = accountHelper.addItem(wx.StaticText(accountBox, label=self._account_status()))
		self.signInButton = accountHelper.addItem(wx.Button(accountBox, label=self._button_label()))
		self.signInButton.Bind(wx.EVT_BUTTON, self.onSignInOut)

		# Translators: label of the web-narration options group in LIMA AI settings.
		narrationSizer = wx.StaticBoxSizer(wx.StaticBox(self, label=_("Web narration")), wx.VERTICAL)
		narrationBox = narrationSizer.GetStaticBox()
		narrationHelper = gui.guiHelper.BoxSizerHelper(narrationBox, sizer=narrationSizer)
		helper.addItem(narrationHelper)
		# Before speaking each update, LIMA can speak a short phrase, play a sound, or say
		# nothing. These three options map to the stored values speech/sound/off, in order.
		self._preAnnounceValues = ["speech", "sound", "off"]
		self.preAnnounceChoice = narrationHelper.addLabeledControl(
			# Translators: label for the web-narration pre-announcement choice.
			_("Announce before each update:"),
			wx.Choice,
			# Translators: the three pre-announcement options, in the order of _preAnnounceValues.
			choices=[_("Speak text"), _("Play a sound"), _("Off")],
		)
		stored = config.conf[CONFIG_SECTION]["webNarrationPreAnnounce"]
		self.preAnnounceChoice.SetSelection(
			self._preAnnounceValues.index(stored) if stored in self._preAnnounceValues else 0
		)
		self.preAnnounceText = narrationHelper.addLabeledControl(
			# Translators: label for the editable spoken pre-announcement text.
			_("Spoken text:"),
			wx.TextCtrl,
			value=config.conf[CONFIG_SECTION]["webNarrationPrefix"],
		)

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
		# Sign-in state is saved by the sign-in flow itself; persist the web-narration options.
		config.conf[CONFIG_SECTION]["webNarrationPreAnnounce"] = self._preAnnounceValues[self.preAnnounceChoice.GetSelection()]
		config.conf[CONFIG_SECTION]["webNarrationPrefix"] = self.preAnnounceText.GetValue()
