# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: the backend's signup guard, from the add-on's side. Standard library
# only; no NVDA imports, so it is testable on its own.
#
# The backend checks a FREE user once, when their first key is minted, and may refuse:
#   403 {"message": "signup_not_allowed"}  - this Google account's email address (a
#        disposable one) will not get a free account. Another Google account will.
#   429 {"message": "signup_limited", "reason": ..., "retry_after": seconds} - too many new
#        accounts from this computer ("device"), this internet connection ("ip"), or from
#        everyone today ("global"). The account is fine and works after the wait.
# This module says so in words a screen-reader user can act on, and supplies the
# pseudonymous device ID the per-computer check counts.

import base64
import hashlib
import json
import logging
import math
import os

log = logging.getLogger(__name__)

SIGNUP_NOT_ALLOWED = "signup_not_allowed"
SIGNUP_LIMITED = "signup_limited"
# The backend no longer accepts this sign-in. Not from the signup guard, but handled with it:
# it is the other failure that signs the user out.
SESSION_EXPIRED = "session_expired"

#: Failures that sign the user out: this account will never work as it is.
SIGN_OUT_CODES = (SIGNUP_NOT_ALLOWED, SESSION_EXPIRED)

# The backend's OWN answers when it rejects the sign-in itself (lima-addon-auth-server's
# authenticate_request). Matched exactly, because the proxy passes OpenRouter's status and
# body straight through: an OpenRouter 401 (its key) or 403 (a flagged image) is the AI
# service failing, not the user's sign-in, and must never sign anyone out.
BACKEND_SIGN_IN_REJECTIONS = frozenset({
	"Missing bearer token",
	"Invalid or expired token",
	"Email not verified",
	"Sign-in provider not allowed",
})


def is_sign_in_rejection(status, message):
	"""True when a 401/403 is the backend refusing the sign-in, not an upstream error."""
	return status in (401, 403) and message in BACKEND_SIGN_IN_REJECTIONS


def token_uid(id_token):
	"""The Firebase uid inside an ID token, or "" if it cannot be read.

	Not verified - the backend does that. It only names which account a request was made as,
	so a failure that arrives late signs out that account and never the one the user has
	switched to since.
	"""
	try:
		payload = id_token.split(".")[1]
		claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
		uid = claims.get("user_id") or claims.get("sub") or ""
		return uid if isinstance(uid, str) else ""
	except Exception:
		return ""

# Mixed into the device ID before hashing, so the add-on's value differs from LIMA Desktop's for
# the same machine and no plain equality matches them. It is a public constant, not a secret:
# anyone who knows a machine's MachineGuid and account can compute either value. Changing it
# gives every computer a new ID, which resets the backend's per-computer counts.
_DEVICE_ID_SALT = "lima-nvda-device-v1"


def device_id():
	"""A pseudonymous identifier for this computer and Windows user, or "" if unavailable.

	Sent as X-LIMA-Device so the backend can limit how many new free accounts are created on
	one computer. It is a SHA-256 of Windows' MachineGuid and the signed-in Windows account,
	salted for this add-on: a pseudonymous, product-specific identifier. The MachineGuid and
	account name are never sent, only the hash. It is not anonymous: it travels with the user's
	sign-in token, and anyone who already knows both inputs can recompute it.

	The Windows account is part of it because of school computer labs, which are often cloned
	from one disk image and can share a MachineGuid. With the account in, students who each
	sign in to Windows as themselves are counted apart, while one person making many accounts
	on their own computer still counts as one computer.

	Never raises: the header is optional, and the backend skips the per-computer check
	without it.
	"""
	try:
		import winreg
		# KEY_WOW64_64KEY: a 32-bit NVDA would otherwise be redirected to WOW6432Node, where
		# MachineGuid does not exist.
		with winreg.OpenKey(
			winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
			winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
		) as key:
			machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
		machine_guid = str(machine_guid).strip().lower()
		if not machine_guid:
			return ""
		account = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
		material = "%s\n%s\n%s" % (_DEVICE_ID_SALT, machine_guid, account.lower())
		return hashlib.sha256(material.encode("utf-8")).hexdigest()
	except Exception:
		log.debug("Could not derive a device ID", exc_info=True)
		return ""


def wait_phrase(seconds, text):
	"""How long to wait, as words to read aloud: "about 3 hours", never "10800 seconds".

	Rounded generously - someone told "about an hour" who tries at 55 minutes and is refused
	again has been told the wrong thing - and vague on purpose, because the backend's figure
	is when a slot opens, not a promise. `text` translates each phrase.
	"""
	try:
		seconds = float(seconds)
	except (TypeError, ValueError):
		seconds = 0
	if not seconds > 0:
		return text("a little while")
	if seconds <= 90:
		return text("about a minute")
	if seconds < 3600:
		return text("about {n} minutes").format(n=math.ceil(seconds / 60))
	# Whole hours, rounded UP like everything else here: 61 to 120 minutes is "about 2 hours".
	# "About an hour" for anything up to 90 minutes sent people back up to half an hour early,
	# to be refused again.
	if seconds == 3600:
		return text("about an hour")
	if seconds < 2 * 86400:
		return text("about {n} hours").format(n=math.ceil(seconds / 3600))
	return text("about {n} days").format(n=math.ceil(seconds / 86400))


def refusal_message(code, reason, retry_after, text):
	"""What the user hears when the backend refuses their free account or their sign-in.

	`text` translates each sentence (the add-on's _status_text). Returns None for any other
	code, so callers fall through to their usual messages.
	"""
	if code == SESSION_EXPIRED:
		# Signed out as this is spoken, like SIGNUP_NOT_ALLOWED.
		return text(
			"Your LIMA AI sign-in is no longer valid, so you have been signed out. "
			"Press NVDA+Alt+A to sign in again."
		)
	if code == SIGNUP_NOT_ALLOWED:
		# The plugin and the settings panel sign the account out as this is spoken.
		return text(
			"LIMA AI cannot create a free account with this email address, so you have been "
			"signed out. Press NVDA+Alt+A to sign in with a different Google account, or contact "
			"Roscommon Systems at hello@roscommonsystems.com."
		)
	if code != SIGNUP_LIMITED:
		return None
	wait = wait_phrase(retry_after, text)
	if reason == "global":
		# The daily cap across everyone. Nothing the user did and no wait worth naming: the cap
		# is a brake for an attack, and it lifts as the day's signups age out.
		return text("LIMA AI can't create new free accounts right now. Please try again later.")
	if reason == "device":
		return text(
			"Too many new LIMA AI accounts have been created on this computer recently. Please "
			"try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com."
		).format(wait=wait)
	return text(
		"Too many new LIMA AI accounts have been created from this internet connection "
		"recently. Please try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com."
	).format(wait=wait)
