import base64
import hashlib
import json
import urllib.error
from contextlib import contextmanager

import pytest

import auth


def _fake_opener(raw_bytes=None, raise_exc=None, capture=None):
	@contextmanager
	def opener(request, timeout=None):
		if capture is not None:
			capture["request"] = request
		if raise_exc is not None:
			raise raise_exc

		class _Resp:
			def read(self_inner):
				return raw_bytes

		yield _Resp()

	return opener


def test_pkce_pair_challenge_is_sha256_of_verifier():
	verifier, challenge = auth._pkce_pair()
	expected = base64.urlsafe_b64encode(
		hashlib.sha256(verifier.encode("ascii")).digest()
	).rstrip(b"=").decode("ascii")
	assert challenge == expected


def test_build_auth_url_uses_pkce_and_loopback_redirect():
	url = auth.build_auth_url("cid", "http://127.0.0.1:5000", "state123", "chal")
	assert url.startswith(auth.GOOGLE_AUTH_ENDPOINT + "?")
	assert "code_challenge=chal" in url
	assert "code_challenge_method=S256" in url
	assert "client_id=cid" in url
	assert "state=state123" in url
	assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A5000" in url


def test_exchange_code_posts_authorization_code_grant():
	captured = {}
	raw = json.dumps({"id_token": "goog-id", "access_token": "a"}).encode("utf-8")
	tokens = auth.exchange_code(
		"cid", "secret", "the-code", "http://127.0.0.1:1", "verifier",
		_opener=_fake_opener(raw_bytes=raw, capture=captured),
	)
	assert tokens["id_token"] == "goog-id"
	body = captured["request"].data.decode("utf-8")
	assert "grant_type=authorization_code" in body
	assert "code=the-code" in body
	assert "code_verifier=verifier" in body


def test_sign_in_with_idp_targets_google_provider_with_api_key():
	captured = {}
	raw = json.dumps({"idToken": "fb", "refreshToken": "r", "localId": "u1"}).encode("utf-8")
	body = auth.sign_in_with_idp("goog-id", "APIKEY", _opener=_fake_opener(raw_bytes=raw, capture=captured))
	assert body["idToken"] == "fb"
	assert captured["request"].full_url.endswith("key=APIKEY")
	payload = json.loads(captured["request"].data.decode("utf-8"))
	assert "providerId=google.com" in payload["postBody"]
	assert payload["returnSecureToken"] is True


def test_session_from_idp_normalises_profile_and_tokens():
	session = auth._session_from_idp({
		"localId": "uid-1",
		"email": "a@b.com",
		"displayName": "Ada",
		"idToken": "tok",
		"refreshToken": "ref",
		"expiresIn": "3600",
	})
	assert session["uid"] == "uid-1"
	assert session["email"] == "a@b.com"
	assert session["displayName"] == "Ada"
	assert session["idToken"] == "tok"
	assert session["refreshToken"] == "ref"
	assert session["expiresAt"] > 0


def test_refresh_id_token_uses_refresh_grant():
	captured = {}
	raw = json.dumps({"id_token": "new", "refresh_token": "r2", "expires_in": "3600"}).encode("utf-8")
	data = auth.refresh_id_token("old-refresh", "APIKEY", _opener=_fake_opener(raw_bytes=raw, capture=captured))
	assert data["id_token"] == "new"
	form = captured["request"].data.decode("utf-8")
	assert "grant_type=refresh_token" in form
	assert "refresh_token=old-refresh" in form


# --- The sign-in profile, recorded by the backend ----------------------------
#
# Since 0.6.0 the add-on no longer writes to Firestore. It POSTs the sign-in to the LIMA
# backend's /sign-in, which writes the profile with its own service account, as
# lima-auth-server does for LIMA desktop: email and name from the verified token, IP from
# its own front end, country from LemonSqueezy or else the Windows region sent here.

@pytest.fixture
def backend(monkeypatch):
	monkeypatch.setattr(auth, "SIGN_IN_URL", "https://backend.example/sign-in")
	monkeypatch.setattr(auth, "ADDON_VERSION", "0.6.0")
	monkeypatch.setattr(auth, "USER_AGENT", "LIMA-NVDA/0.6.0 NVDA/2026.3.1")
	monkeypatch.setattr(auth, "DEVICE_ID", "d" * 64)
	monkeypatch.setattr(auth, "_system_region", lambda: "VN")


def test_record_sign_in_posts_the_token_and_headers_to_the_backend(backend):
	captured = {}
	assert auth.record_sign_in("tok", _opener=_fake_opener(raw_bytes=b'{"recorded": true}', capture=captured)) is True
	request = captured["request"]
	assert request.full_url == "https://backend.example/sign-in"
	assert request.get_method() == "POST"
	headers = {k.lower(): v for k, v in request.header_items()}
	assert headers["authorization"] == "Bearer tok"
	assert headers["user-agent"] == "LIMA-NVDA/0.6.0 NVDA/2026.3.1"
	assert headers["x-lima-addon-version"] == "0.6.0"
	assert headers["x-lima-region"] == "VN"
	assert headers["x-lima-device"] == "d" * 64


def test_record_sign_in_sends_no_profile_of_its_own(backend):
	"""Nothing the server stores comes from the body: the token and our front end say who and where."""
	captured = {}
	auth.record_sign_in("tok", _opener=_fake_opener(raw_bytes=b'{"recorded": true}', capture=captured))
	assert captured["request"].data == b"{}"


def test_record_sign_in_never_touches_firestore(backend):
	captured = {}
	auth.record_sign_in("tok", _opener=_fake_opener(raw_bytes=b'{"recorded": true}', capture=captured))
	assert "firestore.googleapis.com" not in captured["request"].full_url
	assert not hasattr(auth, "FIRESTORE_BASE")
	assert not hasattr(auth, "save_user_login")


def test_an_unknown_region_leaves_the_header_off(backend, monkeypatch):
	monkeypatch.setattr(auth, "_system_region", lambda: "")
	captured = {}
	auth.record_sign_in("tok", _opener=_fake_opener(raw_bytes=b'{"recorded": true}', capture=captured))
	assert "x-lima-region" not in {k.lower() for k, _ in captured["request"].header_items()}


@pytest.mark.parametrize("raise_exc", [
	urllib.error.HTTPError("https://backend", 500, "Internal", {}, None),
	urllib.error.HTTPError("https://backend", 429, "Too Many", {}, None),
	urllib.error.URLError("down"),
	TimeoutError(),
])
def test_a_failure_is_false_and_never_raises(backend, raise_exc):
	"""The user is signed in either way; the profile is only a record of it."""
	assert auth.record_sign_in("tok", _opener=_fake_opener(raise_exc=raise_exc)) is False


@pytest.mark.parametrize("raw", [b'{"recorded": false}', b"not json", b"[]"])
def test_an_unrecorded_answer_is_false(backend, raw):
	assert auth.record_sign_in("tok", _opener=_fake_opener(raw_bytes=raw)) is False


def test_no_backend_url_is_false_without_a_request(monkeypatch):
	monkeypatch.setattr(auth, "SIGN_IN_URL", None)
	assert auth.record_sign_in("tok", _opener=_fake_opener(raise_exc=AssertionError("no request expected"))) is False


def test_run_sign_in_records_through_the_backend(monkeypatch):
	recorded = []
	monkeypatch.setattr(auth, "_open_browser", lambda url: None)
	monkeypatch.setattr(auth, "_wait_for_redirect", lambda server, timeout: ("code", STATE["value"], "Mozilla/5.0"))
	monkeypatch.setattr(auth, "_url_token", lambda n: STATE["value"])
	monkeypatch.setattr(auth, "exchange_code", lambda *a, **k: {"id_token": "goog-id"})
	monkeypatch.setattr(auth, "sign_in_with_idp", lambda *a, **k: {
		"localId": "uid-1", "email": "a@b.com", "displayName": "Ada", "idToken": "fb-tok",
		"refreshToken": "ref", "expiresIn": "3600",
	})
	monkeypatch.setattr(auth, "record_sign_in", lambda token, _opener=None: recorded.append(token) or True)
	session = auth.run_sign_in(auth.FirebaseConfig("cid", "sec", "key", "proj"), open_browser=False)
	assert recorded == ["fb-tok"]
	assert session["uid"] == "uid-1"


def test_run_sign_in_succeeds_when_the_backend_cannot_record(monkeypatch):
	monkeypatch.setattr(auth, "_open_browser", lambda url: None)
	monkeypatch.setattr(auth, "_wait_for_redirect", lambda server, timeout: ("code", STATE["value"], ""))
	monkeypatch.setattr(auth, "_url_token", lambda n: STATE["value"])
	monkeypatch.setattr(auth, "exchange_code", lambda *a, **k: {"id_token": "goog-id"})
	monkeypatch.setattr(auth, "sign_in_with_idp", lambda *a, **k: {"localId": "uid-1", "idToken": "fb-tok", "expiresIn": "3600"})
	monkeypatch.setattr(auth, "record_sign_in", lambda token, _opener=None: False)
	assert auth.run_sign_in(auth.FirebaseConfig("cid", "sec", "key", "proj"), open_browser=False)["uid"] == "uid-1"


STATE = {"value": "fixed-state"}


class _FakeKernel32:
	def __init__(self, value):
		self.value = value

	def GetUserDefaultGeoName(self, buf, size):
		buf.value = self.value
		return len(self.value) + 1 if self.value else 0


@pytest.mark.parametrize("windows_value,expected", [
	("VN", "VN"), ("ie", "IE"), ("001", ""), ("419", ""), ("", ""), ("USA", ""),
])
def test_system_region_returns_only_a_country(monkeypatch, windows_value, expected):
	"""Copied from LIMA desktop: UN M.49 codes like 001 (World) are not countries."""
	import ctypes
	monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": _FakeKernel32(windows_value)})(), raising=False)
	assert auth._system_region() == expected


def test_system_region_is_blank_when_windows_cannot_answer(monkeypatch):
	import ctypes

	class _Broken:
		def GetUserDefaultGeoName(self, buf, size):
			raise OSError("not available on this Windows")

	monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": _Broken()})(), raising=False)
	assert auth._system_region() == ""


def test_parse_request_extracts_query_and_user_agent():
	raw = (
		b"GET /?code=abc&state=xyz HTTP/1.1\r\n"
		b"Host: 127.0.0.1:5000\r\n"
		b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0\r\n"
		b"Accept: text/html\r\n\r\n"
	)
	params, user_agent = auth._parse_request(raw)
	assert params["code"] == ["abc"]
	assert params["state"] == ["xyz"]
	assert user_agent == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"


def test_network_failure_raises_network_code():
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	with pytest.raises(auth.AuthError) as exc:
		auth.sign_in_with_idp("goog-id", "APIKEY", _opener=opener)
	assert exc.value.code == "network"


def test_http_failure_raises_auth_error_code():
	http_error = urllib.error.HTTPError("https://identitytoolkit", 400, "Bad Request", {}, None)
	with pytest.raises(auth.AuthError) as exc:
		auth.sign_in_with_idp("goog-id", "APIKEY", _opener=_fake_opener(raise_exc=http_error))
	assert exc.value.code == "auth_error"


def test_run_sign_in_without_config_raises_config_code():
	cfg = auth.FirebaseConfig("", "", "", "")
	with pytest.raises(auth.AuthError) as exc:
		auth.run_sign_in(cfg, open_browser=False)
	assert exc.value.code == "config"
