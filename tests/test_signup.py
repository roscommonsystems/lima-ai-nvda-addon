"""The backend's signup guard, from the add-on's side: the device ID it sends, how vision and
usage recognise a refusal, and what a screen-reader user hears."""

import io
import json
import re
import sys
import types
import urllib.error
from contextlib import contextmanager
from unittest import mock

import pytest

import announcements
import signup
import usage
import vision
import webnarration

DEVICE = "ab" * 32


@pytest.fixture(autouse=True)
def _endpoints(monkeypatch):
	monkeypatch.setattr(vision, "ENDPOINT_URL", "https://backend.test/v1/chat/completions")
	monkeypatch.setattr(usage, "ENDPOINT_URL", "https://backend.test/usage")
	monkeypatch.setattr(vision, "DEVICE_ID", "")
	monkeypatch.setattr(usage, "DEVICE_ID", "")


def _http_error(code, body, headers=None):
	return urllib.error.HTTPError("https://backend.test", code, "err", headers or {}, io.BytesIO(json.dumps(body).encode()))


def _opener(raise_exc=None, raw=b"{}", seen=None):
	@contextmanager
	def opener(request, timeout=None):
		if seen is not None:
			seen.append(request)
		if raise_exc is not None:
			raise raise_exc

		class _Resp:
			def read(self):
				return raw
		yield _Resp()
	return opener


def _english(message):
	return message


def _text(language):
	return lambda message: announcements.status_text(message, language, _english)


# --- device_id ----------------------------------------------------------------------------

@pytest.fixture
def registry(monkeypatch):
	"""A stand-in winreg module holding HKLM\\SOFTWARE\\Microsoft\\Cryptography; set .guid to
	what it holds. A fake module rather than the real one patched, so these run on any OS:
	signup.device_id() imports winreg when called, and Linux has none."""
	state = mock.Mock(guid="AAAA1111-2222-3333-4444-555566667777", calls=[])
	key = mock.MagicMock()
	key.__enter__.return_value = key

	def open_key(*args):
		state.calls.append(args)
		return key

	def query(_key, name):
		if isinstance(state.guid, Exception):
			raise state.guid
		return state.guid, 1

	fake = types.ModuleType("winreg")
	fake.HKEY_LOCAL_MACHINE = 0x80000002
	fake.KEY_READ = 0x20019
	fake.KEY_WOW64_64KEY = 0x0100
	fake.OpenKey = open_key
	fake.QueryValueEx = query
	monkeypatch.setitem(sys.modules, "winreg", fake)
	state.module = fake
	return state


def test_device_id_is_a_sha256_without_the_guid_in_it(registry):
	value = signup.device_id()
	assert re.fullmatch(r"[0-9a-f]{64}", value)
	assert "aaaa1111" not in value


def test_device_id_is_stable(registry):
	assert signup.device_id() == signup.device_id()


def test_two_windows_accounts_on_one_cloned_pc_get_different_ids(registry, monkeypatch):
	"""School labs cloned from one disk image share a MachineGuid."""
	monkeypatch.setenv("USERNAME", "student1")
	first = signup.device_id()
	monkeypatch.setenv("USERNAME", "student2")
	assert signup.device_id() != first


def test_device_id_differs_from_lima_desktops(registry, monkeypatch):
	"""Salted per product, so the two products' IDs for one computer cannot be linked."""
	ours = signup.device_id()
	monkeypatch.setattr(signup, "_DEVICE_ID_SALT", "lima-desktop-device-v1")
	assert signup.device_id() != ours


def test_device_id_reads_the_64_bit_registry_view(registry):
	"""NVDA may be 32-bit, and would otherwise be redirected to WOW6432Node."""
	signup.device_id()
	assert registry.calls[0][3] & registry.module.KEY_WOW64_64KEY


@pytest.mark.parametrize("guid", [OSError("no key"), "", "  "])
def test_an_unreadable_guid_gives_no_id_rather_than_raising(registry, guid):
	registry.guid = guid
	assert signup.device_id() == ""


# --- wait_phrase and refusal_message ----------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
	(None, "a little while"), ("soon", "a little while"), (0, "a little while"),
	(30, "about a minute"), (91, "about 2 minutes"), (3600, "about an hour"),
	(3601, "about 2 hours"), (5400, "about 2 hours"), (5401, "about 2 hours"), (7201, "about 3 hours"), (86000, "about 24 hours"), (2592000, "about 30 days"),
])
def test_wait_phrase_reads_as_words(seconds, expected):
	assert signup.wait_phrase(seconds, _english) == expected


def test_a_refused_address_says_to_sign_in_with_another_account():
	message = signup.refusal_message("signup_not_allowed", None, None, _english)
	assert "signed out" in message and "different Google account" in message and "NVDA+Alt+A" in message


@pytest.mark.parametrize("reason,where", [
	("device", "this computer"), ("ip", "this internet connection"), ("", "this internet connection"),
])
def test_a_limit_says_where_and_how_long(reason, where):
	message = signup.refusal_message("signup_limited", reason, 7200, _english)
	assert where in message and "about 2 hours" in message


def test_the_daily_cap_just_says_try_again_later():
	message = signup.refusal_message("signup_limited", "global", 600, _english)
	assert message == "LIMA AI can't create new free accounts right now. Please try again later."


def test_other_codes_are_left_to_the_usual_messages():
	assert signup.refusal_message("rate_limited", None, 30, _english) is None


@pytest.mark.parametrize("language", ["vi", "tl"])
def test_every_refusal_is_translated_with_its_placeholders(language):
	text = _text(language)
	for code, reason in (("signup_not_allowed", None), ("signup_limited", "device"),
						 ("signup_limited", "ip"), ("signup_limited", "global")):
		message = signup.refusal_message(code, reason, 7200, text)
		assert "LIMA AI" in message
		if reason != "global":
			assert "hello@roscommonsystems.com" in message
		assert "{" not in message
		assert message != signup.refusal_message(code, reason, 7200, _english)
	for seconds in (None, 30, 300, 3600, 7200, 200000):
		assert signup.wait_phrase(seconds, text) != signup.wait_phrase(seconds, _english)


# --- vision -----------------------------------------------------------------------------

def test_vision_sends_the_device_id_when_set(monkeypatch):
	monkeypatch.setattr(vision, "DEVICE_ID", DEVICE)
	seen = []
	raw = json.dumps({"choices": [{"message": {"content": "A form."}}]}).encode()
	vision.describe_image(b"png", "tok", _opener=_opener(raw=raw, seen=seen))
	assert seen[0].get_header("X-lima-device") == DEVICE


def test_vision_leaves_the_header_off_without_one():
	seen = []
	raw = json.dumps({"choices": [{"message": {"content": "A form."}}]}).encode()
	vision.describe_image(b"png", "tok", _opener=_opener(raw=raw, seen=seen))
	assert seen[0].get_header("X-lima-device") is None


def test_vision_403_signup_not_allowed_has_its_own_code():
	error = _http_error(403, {"message": "signup_not_allowed", "reason": "email_domain"})
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", "tok", _opener=_opener(raise_exc=error))
	assert exc.value.code == "signup_not_allowed"


@pytest.mark.parametrize("status,body", [
	(401, {"message": "Invalid or expired token"}),
	(403, {"message": "Email not verified"}),
	(403, {"message": "Sign-in provider not allowed"}),
])
def test_vision_a_rejected_sign_in_says_sign_in_again_not_api_error(status, body):
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", "tok", _opener=_opener(raise_exc=_http_error(status, body)))
	assert exc.value.code == "session_expired"


def test_vision_429_signup_limited_carries_the_reason_and_the_wait():
	error = _http_error(429, {"message": "signup_limited", "reason": "device", "retry_after": 3000}, {"Retry-After": "3000"})
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", "tok", _opener=_opener(raise_exc=error))
	assert (exc.value.code, exc.value.reason, exc.value.retry_after) == ("signup_limited", "device", 3000)


def test_vision_a_plain_429_is_still_rate_limited():
	error = _http_error(429, {"message": "rate_limited", "retry_after": 12})
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", "tok", _opener=_opener(raise_exc=error))
	assert exc.value.code == "rate_limited"


# --- usage ------------------------------------------------------------------------------

def test_usage_sends_the_device_id_when_set(monkeypatch):
	monkeypatch.setattr(usage, "DEVICE_ID", DEVICE)
	seen = []
	usage.fetch_credit_usage("tok", _opener=_opener(raw=b'{"usage_percent": 1}', seen=seen))
	assert seen[0].get_header("X-lima-device") == DEVICE


def test_usage_403_signup_not_allowed():
	error = _http_error(403, {"message": "signup_not_allowed"})
	assert usage.fetch_credit_usage("tok", _opener=_opener(raise_exc=error)) == {"valid": False, "error": "signup_not_allowed", "uid": ""}


def test_usage_429_signup_limited():
	error = _http_error(429, {"message": "signup_limited", "reason": "ip", "retry_after": 600})
	assert usage.fetch_credit_usage("tok", _opener=_opener(raise_exc=error)) == {
		"valid": False, "error": "signup_limited", "reason": "ip", "retry_after": 600,
	}


@pytest.mark.parametrize("status", [401, 403])
def test_usage_a_rejected_sign_in_says_sign_in_again(status):
	error = _http_error(status, {"message": "Invalid or expired token"})
	assert usage.fetch_credit_usage("tok", _opener=_opener(raise_exc=error)) == {"valid": False, "error": "session_expired", "uid": ""}


def test_usage_a_plain_429_is_still_rate_limited():
	error = _http_error(429, {"message": "rate_limited", "retry_after": 12})
	assert usage.fetch_credit_usage("tok", _opener=_opener(raise_exc=error)) == {"valid": False, "error": "rate_limited"}


# --- web narration --------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["signup_not_allowed", "signup_limited", "session_expired"])
def test_narration_stops_on_a_signup_refusal_rather_than_retrying_every_tick(code):
	assert code in webnarration.WebNarrator.STOPPING_CODES


# --- Review fixes: whose sign-in failed, and was it the sign-in at all ---------------------------

def _token(uid):
	"""A Firebase-shaped ID token for `uid` (unsigned; nothing here verifies it)."""
	import base64

	def part(obj):
		return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
	return "%s.%s.sig" % (part({"alg": "RS256"}), part({"user_id": uid, "sub": uid}))


def test_token_uid_reads_the_account_from_a_token():
	assert signup.token_uid(_token("uid-a")) == "uid-a"


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.%%%.c", None, "a.e30.c"])
def test_token_uid_is_empty_when_it_cannot_tell(token):
	assert signup.token_uid(token) == ""


@pytest.mark.parametrize("status,body", [
	(401, {"error": {"code": 401, "message": "No auth credentials found"}}),
	(403, {"error": {"code": 403, "message": "Input was flagged by moderation"}}),
	(401, {"message": "something else"}),
])
def test_vision_an_openrouter_401_or_403_is_an_api_error_not_a_sign_out(status, body):
	"""The proxy passes OpenRouter's status through. A flagged image or a bad upstream key must
	never sign the user out of a Google account that is fine."""
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", _token("uid-a"), _opener=_opener(raise_exc=_http_error(status, body)))
	assert exc.value.code == "api_error"


def test_vision_a_rejection_names_the_account_it_was_for():
	error = _http_error(401, {"message": "Invalid or expired token"})
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", _token("uid-a"), _opener=_opener(raise_exc=error))
	assert (exc.value.code, exc.value.uid) == ("session_expired", "uid-a")


def test_vision_a_refused_address_names_the_account_it_was_for():
	error = _http_error(403, {"message": "signup_not_allowed"})
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"png", _token("uid-a"), _opener=_opener(raise_exc=error))
	assert (exc.value.code, exc.value.uid) == ("signup_not_allowed", "uid-a")


def test_usage_an_openrouter_403_is_unavailable_not_a_sign_out():
	error = _http_error(403, {"error": {"code": 403, "message": "Forbidden"}})
	assert usage.fetch_credit_usage(_token("uid-a"), _opener=_opener(raise_exc=error)) == {"valid": False, "error": "unavailable"}


def test_usage_a_rejection_names_the_account_it_was_for():
	error = _http_error(403, {"message": "Email not verified"})
	assert usage.fetch_credit_usage(_token("uid-a"), _opener=_opener(raise_exc=error)) == {
		"valid": False, "error": "session_expired", "uid": "uid-a",
	}


def test_every_backend_sign_in_rejection_is_recognised():
	"""Kept in step with lima-addon-auth-server's authenticate_request."""
	for message in ("Missing bearer token", "Invalid or expired token", "Email not verified", "Sign-in provider not allowed"):
		assert signup.is_sign_in_rejection(401, message) or signup.is_sign_in_rejection(403, message)
	assert not signup.is_sign_in_rejection(500, "Invalid or expired token")
