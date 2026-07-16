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


def test_get_user_document_returns_none_on_404():
	http_error = urllib.error.HTTPError("https://firestore", 404, "Not Found", {}, None)
	result = auth.get_user_document("proj", "uid", "tok", _opener=_fake_opener(raise_exc=http_error))
	assert result is None


def test_save_user_login_new_user_writes_flat_created_at():
	captured = {}
	auth.save_user_login(
		"proj", "uid-9", "tok", "a@b.com", "Ada",
		include_created=True, now="2026-07-13T00:00:00.000000Z",
		_opener=_fake_opener(raw_bytes=b"{}", capture=captured),
	)
	request = captured["request"]
	assert request.get_method() == "PATCH"
	assert request.headers["Authorization"] == "Bearer tok"
	assert "updateMask.fieldPaths=createdAt" in request.full_url
	body = json.loads(request.data.decode("utf-8"))
	assert body["fields"]["email"]["stringValue"] == "a@b.com"
	assert body["fields"]["createdAt"]["timestampValue"] == "2026-07-13T00:00:00.000000Z"


def test_save_user_login_uses_named_database_in_url():
	captured = {}
	auth.save_user_login(
		"proj", "uid-9", "tok", "a@b.com", "Ada",
		database_id="lima-nvda-addon-firestore-db",
		_opener=_fake_opener(raw_bytes=b"{}", capture=captured),
	)
	assert "/databases/lima-nvda-addon-firestore-db/documents/users/uid-9" in captured["request"].full_url


def test_save_user_login_writes_environment_fields_when_present():
	captured = {}
	auth.save_user_login(
		"proj", "uid-9", "tok", "a@b.com", "Ada",
		ip_address="203.0.113.5", system_language="en-US",
		user_agent="Mozilla/5.0 (Windows NT 10.0)", country="SG",
		_opener=_fake_opener(raw_bytes=b"{}", capture=captured),
	)
	request = captured["request"]
	for path in ("ipAddress", "systemLanguage", "userAgent", "country"):
		assert "updateMask.fieldPaths=" + path in request.full_url
	body = json.loads(request.data.decode("utf-8"))
	assert body["fields"]["ipAddress"]["stringValue"] == "203.0.113.5"
	assert body["fields"]["systemLanguage"]["stringValue"] == "en-US"
	assert body["fields"]["userAgent"]["stringValue"] == "Mozilla/5.0 (Windows NT 10.0)"
	assert body["fields"]["country"]["stringValue"] == "SG"


def test_save_user_login_omits_environment_fields_when_blank():
	captured = {}
	auth.save_user_login(
		"proj", "uid-9", "tok", "a@b.com", "Ada",
		_opener=_fake_opener(raw_bytes=b"{}", capture=captured),
	)
	request = captured["request"]
	body = json.loads(request.data.decode("utf-8"))
	for path in ("ipAddress", "systemLanguage", "userAgent", "country"):
		assert path not in body["fields"]
		assert "updateMask.fieldPaths=" + path not in request.full_url


def test_save_user_login_returning_user_omits_created_at():
	captured = {}
	auth.save_user_login(
		"proj", "uid-9", "tok", "a@b.com", "Ada",
		include_created=False,
		_opener=_fake_opener(raw_bytes=b"{}", capture=captured),
	)
	assert "createdAt" not in captured["request"].full_url
	body = json.loads(captured["request"].data.decode("utf-8"))
	assert "createdAt" not in body["fields"]
	assert "lastLoginAt" in body["fields"]


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


def test_fetch_ip_and_country_parses_cloudflare_trace():
	trace = b"fl=123abc\nh=www.cloudflare.com\nip=203.0.113.9\nts=1752660000.1\nloc=SG\n"
	assert auth._fetch_ip_and_country(_opener=_fake_opener(raw_bytes=trace)) == ("203.0.113.9", "SG")


def test_fetch_ip_and_country_blank_when_lines_missing():
	assert auth._fetch_ip_and_country(_opener=_fake_opener(raw_bytes=b"fl=1\nh=x\n")) == ("", "")


def test_fetch_ip_and_country_blank_on_failure():
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("no net"))
	assert auth._fetch_ip_and_country(_opener=opener) == ("", "")


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
