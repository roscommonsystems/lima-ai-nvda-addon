# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: Google SSO via Firebase Authentication.
# Standard library only; no NVDA imports so it stays unit-testable.
#
# Flow (all client-side, no backend):
#   1. Google OAuth 2.0 "installed app" loopback flow  -> Google ID token
#   2. Firebase accounts:signInWithIdp (REST)          -> Firebase idToken + refreshToken + profile
#   3. Firestore REST write of users/{uid}             -> email, displayName, createdAt, lastLoginAt
# The Firebase idToken is refreshed via securetoken.googleapis.com.

import base64
import collections
import datetime
import hashlib
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

# NVDA ships a trimmed Python that omits some stdlib modules (e.g. `secrets`,
# and likely `webbrowser`/`http.server`). This module deliberately sticks to
# modules that are always present: os.urandom for randomness, a raw socket for
# the loopback listener, and os.startfile to open the default browser.

log = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SIGN_IN_WITH_IDP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1"

OAUTH_SCOPES = ["openid", "email", "profile"]

#: Project constants needed to run the flow. Values come from firebase_config.py.
#: database_id is "(default)" unless the project uses a named Firestore database.
#: users_collection isolates dev from prod (users_dev vs users) and MUST match the
#: auth server's USERS_COLLECTION so the profile and the OpenRouter fields land in the
#: same user document.
FirebaseConfig = collections.namedtuple(
	"FirebaseConfig",
	["client_id", "client_secret", "api_key", "project_id", "database_id", "users_collection"],
	defaults=["(default)", "users"],
)


class AuthError(Exception):
	"""A failure with a stable code the caller maps to a user-facing message.

	code is one of: "config", "network", "auth_error", "cancelled", "timeout".
	"""

	def __init__(self, code):
		super().__init__(code)
		self.code = code


# --- HTTP plumbing -----------------------------------------------------------

def _send(request, timeout, _opener, not_found_ok=False):
	"""Run one HTTP request, returning raw bytes (or None on an allowed 404).

	Maps transport failures to a stable AuthError while logging the real cause,
	mirroring vision.describe_image. `_opener` is injectable for tests.
	"""
	opener = _opener or urllib.request.urlopen
	try:
		with opener(request, timeout=timeout) as response:
			return response.read()
	except urllib.error.HTTPError as e:
		if not_found_ok and getattr(e, "code", None) == 404:
			return None
		detail = ""
		try:
			detail = e.read().decode("utf-8", "replace")[:500]
		except Exception:
			pass
		log.error("LIMA auth HTTP error %s: %s", getattr(e, "code", "?"), detail)
		raise AuthError("auth_error") from e
	except (urllib.error.URLError, TimeoutError, OSError) as e:
		log.error("LIMA auth could not reach the service: %r", e)
		raise AuthError("network") from e


def _parse_json(raw):
	try:
		return json.loads(raw.decode("utf-8"))
	except (ValueError, AttributeError) as e:
		log.error("LIMA auth received a non-JSON response: %r", e)
		raise AuthError("auth_error") from e


def _post_form(url, fields, timeout, _opener):
	data = urllib.parse.urlencode(fields).encode("utf-8")
	request = urllib.request.Request(
		url,
		data=data,
		headers={"Content-Type": "application/x-www-form-urlencoded"},
		method="POST",
	)
	return _parse_json(_send(request, timeout, _opener))


def _post_json(url, payload, timeout, _opener, id_token=None):
	data = json.dumps(payload).encode("utf-8")
	headers = {"Content-Type": "application/json"}
	if id_token:
		headers["Authorization"] = "Bearer " + id_token
	request = urllib.request.Request(url, data=data, headers=headers, method="POST")
	return _parse_json(_send(request, timeout, _opener))


# --- OAuth / PKCE ------------------------------------------------------------

def _url_token(n_bytes):
	"""Return n_bytes of OS randomness as a URL-safe, unpadded string."""
	return base64.urlsafe_b64encode(os.urandom(n_bytes)).rstrip(b"=").decode("ascii")


def _pkce_pair():
	"""Return (verifier, challenge) for an OAuth 2.0 PKCE exchange (RFC 7636)."""
	verifier = _url_token(32)
	digest = hashlib.sha256(verifier.encode("ascii")).digest()
	challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
	return verifier, challenge


def build_auth_url(client_id, redirect_uri, state, code_challenge, scopes=OAUTH_SCOPES):
	"""Build the Google authorization URL the user's browser is sent to."""
	params = {
		"client_id": client_id,
		"redirect_uri": redirect_uri,
		"response_type": "code",
		"scope": " ".join(scopes),
		"state": state,
		"code_challenge": code_challenge,
		"code_challenge_method": "S256",
		"access_type": "offline",
		"prompt": "consent select_account",
	}
	return GOOGLE_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


def exchange_code(client_id, client_secret, code, redirect_uri, code_verifier, timeout=30, _opener=None):
	"""Exchange an OAuth authorization code for tokens (incl. Google id_token)."""
	fields = {
		"client_id": client_id,
		"code": code,
		"code_verifier": code_verifier,
		"grant_type": "authorization_code",
		"redirect_uri": redirect_uri,
	}
	if client_secret:
		fields["client_secret"] = client_secret
	return _post_form(GOOGLE_TOKEN_ENDPOINT, fields, timeout, _opener)


# --- Firebase ----------------------------------------------------------------

def sign_in_with_idp(google_id_token, api_key, request_uri="http://localhost", timeout=30, _opener=None):
	"""Exchange a Google id_token for a Firebase session. Returns the raw body."""
	url = SIGN_IN_WITH_IDP_URL + "?key=" + urllib.parse.quote(api_key)
	payload = {
		"postBody": "id_token=%s&providerId=google.com" % google_id_token,
		"requestUri": request_uri,
		"returnIdpCredential": True,
		"returnSecureToken": True,
	}
	return _post_json(url, payload, timeout, _opener)


def refresh_id_token(refresh_token, api_key, timeout=30, _opener=None):
	"""Trade a refresh token for a fresh Firebase id_token."""
	url = SECURE_TOKEN_URL + "?key=" + urllib.parse.quote(api_key)
	return _post_form(url, {"grant_type": "refresh_token", "refresh_token": refresh_token}, timeout, _opener)


def _session_from_idp(body):
	"""Normalise a signInWithIdp response into our internal session dict."""
	expires_in = int(body.get("expiresIn", "3600"))
	return {
		"uid": body.get("localId", ""),
		"email": body.get("email", ""),
		"displayName": body.get("displayName") or body.get("fullName") or "",
		"idToken": body.get("idToken", ""),
		"refreshToken": body.get("refreshToken", ""),
		"expiresAt": time.time() + expires_in - 30,
	}


# --- Firestore ---------------------------------------------------------------

def _now_rfc3339():
	return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_user_document(project_id, uid, id_token, database_id="(default)", collection="users", timeout=30, _opener=None):
	"""Return the {collection}/{uid} document, or None if it does not exist yet."""
	url = "%s/projects/%s/databases/%s/documents/%s/%s" % (
		FIRESTORE_BASE, project_id, database_id, collection, urllib.parse.quote(uid),
	)
	request = urllib.request.Request(
		url, headers={"Authorization": "Bearer " + id_token}, method="GET"
	)
	raw = _send(request, timeout, _opener, not_found_ok=True)
	if raw is None:
		return None
	return _parse_json(raw)


def save_user_login(project_id, uid, id_token, email, display_name, include_created=False, database_id="(default)", collection="users", ip_address="", system_language="", user_agent="", country="", now=None, timeout=30, _opener=None):
	"""Upsert the flat profile fields on users/{uid}, touching only what we set.

	An updateMask lists exactly the fields written, so any other fields on the
	document are preserved. createdAt is written only on the first sign-in;
	ip_address/system_language/user_agent/country are written only when known.
	"""
	now = now or _now_rfc3339()
	fields = {
		"email": {"stringValue": email},
		"displayName": {"stringValue": display_name},
		"lastLoginAt": {"timestampValue": now},
	}
	mask = ["email", "displayName", "lastLoginAt"]
	if include_created:
		fields["createdAt"] = {"timestampValue": now}
		mask.append("createdAt")
	# Environment fields: only write the ones we actually captured, so a failed
	# lookup never overwrites a previously stored value with a blank.
	for name, value in (("ipAddress", ip_address), ("systemLanguage", system_language), ("userAgent", user_agent), ("country", country)):
		if value:
			fields[name] = {"stringValue": value}
			mask.append(name)

	query = "&".join("updateMask.fieldPaths=" + p for p in mask)
	url = "%s/projects/%s/databases/%s/documents/%s/%s?%s" % (
		FIRESTORE_BASE, project_id, database_id, collection, urllib.parse.quote(uid), query,
	)
	data = json.dumps({"fields": fields}).encode("utf-8")
	request = urllib.request.Request(
		url,
		data=data,
		headers={"Content-Type": "application/json", "Authorization": "Bearer " + id_token},
		method="PATCH",
	)
	return _parse_json(_send(request, timeout, _opener))


def _store_user(config, session, _opener=None):
	existing = get_user_document(
		config.project_id, session["uid"], session["idToken"],
		database_id=config.database_id, collection=config.users_collection, _opener=_opener,
	)
	has_created = bool(existing and "createdAt" in existing.get("fields", {}))
	save_user_login(
		config.project_id,
		session["uid"],
		session["idToken"],
		session["email"],
		session["displayName"],
		include_created=not has_created,
		database_id=config.database_id,
		collection=config.users_collection,
		ip_address=session.get("ipAddress", ""),
		system_language=session.get("systemLanguage", ""),
		user_agent=session.get("userAgent", ""),
		country=session.get("country", ""),
		_opener=_opener,
	)


# --- Loopback sign-in --------------------------------------------------------

_CALLBACK_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LIMA AI</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 24px;
    background: #ffffff; color: #1f2430;
  }
  .wrap { width: 100%; max-width: 420px; text-align: center; }
  .logo {
    display: block; margin: 0 auto 26px;
    max-width: 160px; max-height: 96px; width: auto; height: auto;
  }
  h1 { font-size: 23px; margin: 0 0 10px; font-weight: 650; letter-spacing: -.01em; }
  p { margin: 0; font-size: 15px; line-height: 1.55; color: #5a6072; }
  .brand {
    margin-top: 26px; font-size: 12px; font-weight: 600;
    letter-spacing: .16em; text-transform: uppercase; color: #9aa0b0;
  }
</style>
</head>
<body>
  <main class="wrap">
    <!--BADGE-->
    <h1>Signed in to LIMA AI</h1>
    <p>You're all set. You can close this tab and return to NVDA.</p>
    <div class="brand">Roscommon Systems</div>
  </main>
</body>
</html>"""

# Shown only when no logo file is found next to this module.
_FALLBACK_BADGE = (
	'<svg class="logo" viewBox="0 0 24 24" width="76" height="76" '
	'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
	'<circle cx="12" cy="12" r="11" fill="#1f9d6f"/>'
	'<path d="M7 12.4l3.3 3.3L17 9" fill="none" stroke="#ffffff" '
	'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


_LOGO_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".ico": "image/x-icon"}

#: Logo filenames to look for, in order of preference.
_LOGO_CANDIDATES = ("roscommon_logo_favicon.ico", "circular_logo_teal.png", "logo.svg", "logo.png", "logo.jpg", "logo.jpeg")


def _logo_data_uri():
	"""Return this add-on's logo as a data: URI, or "" if no logo file is found.

	The loopback server serves only the one HTML response and cannot serve asset
	files, so the logo must be embedded inline. Files are looked for in the
	add-on's assets folder (addon/assets, i.e. ../../assets from this module) and
	then next to this module.
	"""
	here = os.path.dirname(os.path.abspath(__file__))
	for directory in (os.path.join(here, "..", "..", "assets"), here):
		for name in _LOGO_CANDIDATES:
			path = os.path.join(directory, name)
			try:
				with open(path, "rb") as fh:
					data = fh.read()
			except OSError:
				continue
			mime = _LOGO_MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
			return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
	return ""


def _build_callback_body():
	logo = _logo_data_uri()
	badge = ('<img class="logo" src="%s" alt="LIMA AI">' % logo) if logo else _FALLBACK_BADGE
	return _CALLBACK_TEMPLATE.replace("<!--BADGE-->", badge).encode("utf-8")


_CALLBACK_BODY = _build_callback_body()

_CALLBACK_RESPONSE = (
	b"HTTP/1.1 200 OK\r\n"
	b"Content-Type: text/html; charset=utf-8\r\n"
	b"Content-Length: %d\r\n"
	b"Connection: close\r\n\r\n" % len(_CALLBACK_BODY)
) + _CALLBACK_BODY


def _open_browser(url):
	"""Open the default browser without the webbrowser module (often absent)."""
	try:
		os.startfile(url)  # Windows: hands the URL to the default browser
		return
	except (AttributeError, OSError):
		pass
	try:
		import webbrowser
		webbrowser.open(url)
	except Exception:
		log.error("LIMA auth could not open a browser for sign-in")


def _parse_request(raw):
	"""Parse a loopback HTTP request into (query_params, user_agent).

	The redirect request is sent by the user's real browser, so its User-Agent
	header is a genuine browser UA string we can record.
	"""
	head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
	lines = head.split("\r\n")
	try:
		target = lines[0].split(" ")[1]  # e.g. /?code=...&state=...
	except IndexError:
		return {}, ""
	params = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
	user_agent = ""
	for line in lines[1:]:
		name, sep, value = line.partition(":")
		if sep and name.strip().lower() == "user-agent":
			user_agent = value.strip()
			break
	return params, user_agent


def _wait_for_redirect(server, timeout):
	"""Accept loopback connections until Google's redirect arrives.

	Returns (code, state, user_agent); raises AuthError on denial or timeout.
	"""
	deadline = time.time() + timeout
	while time.time() < deadline:
		server.settimeout(max(0.5, deadline - time.time()))
		try:
			conn, _addr = server.accept()
		except (socket.timeout, TimeoutError):
			continue
		try:
			params, user_agent = _parse_request(conn.recv(65536))
			conn.sendall(_CALLBACK_RESPONSE)
		finally:
			conn.close()
		if "error" in params:
			raise AuthError("cancelled")
		if "code" in params:
			return params["code"][0], params.get("state", [None])[0], user_agent
	raise AuthError("timeout")


IP_SERVICE_URL = "https://www.cloudflare.com/cdn-cgi/trace"


def _fetch_ip_and_country(timeout=5, _opener=None):
	"""Best-effort (public_ip, country) via Cloudflare's trace; ("", "") on failure.

	A desktop process cannot see its own public IP, so this makes one small
	outbound request. Cloudflare's trace returns "key=value" lines; we read "ip="
	and "loc=" (a two-letter country code). It never raises — both are optional.
	"""
	try:
		opener = _opener or urllib.request.urlopen
		request = urllib.request.Request(IP_SERVICE_URL, headers={"User-Agent": "LIMA-NVDA-Addon"})
		with opener(request, timeout=timeout) as response:
			text = response.read().decode("ascii", "replace")
		values = {}
		for line in text.splitlines():
			key, sep, value = line.partition("=")
			if sep:
				values[key] = value.strip()
		ip = values.get("ip", "")
		country = values.get("loc", "")
		return (ip if 0 < len(ip) <= 45 else ""), (country if 0 < len(country) <= 8 else "")
	except Exception as e:
		log.info("LIMA auth could not determine public IP/country: %r", e)
		return "", ""


def _system_language():
	"""Return the Windows UI locale as a BCP-47 tag (e.g. "en-US"); "" if unknown."""
	try:
		import ctypes
		buf = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
		if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
			return buf.value
	except Exception:
		pass
	try:
		import locale
		return locale.getdefaultlocale()[0] or ""
	except Exception:
		return ""


def run_sign_in(config, timeout=180, open_browser=True, _opener=None):
	"""Drive the full Google SSO flow and return a session dict.

	Opens the user's default browser, waits for the loopback redirect, exchanges
	the code for a Firebase session, and records the user in Firestore. Blocks
	until the user finishes in the browser, so call it off NVDA's main thread.
	"""
	if not (config.client_id and config.api_key and config.project_id):
		raise AuthError("config")

	verifier, challenge = _pkce_pair()
	state = _url_token(18)

	server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	try:
		server.bind(("127.0.0.1", 0))
		server.listen(1)
		redirect_uri = "http://127.0.0.1:%d" % server.getsockname()[1]

		auth_url = build_auth_url(config.client_id, redirect_uri, state, challenge)
		log.info("LIMA auth opening browser for Google sign-in")
		if open_browser:
			_open_browser(auth_url)

		code, got_state, user_agent = _wait_for_redirect(server, timeout)
	finally:
		server.close()

	if got_state != state:
		log.error("LIMA auth state mismatch; possible CSRF, aborting")
		raise AuthError("auth_error")

	tokens = exchange_code(
		config.client_id, config.client_secret, code, redirect_uri, verifier, _opener=_opener
	)
	google_id_token = tokens.get("id_token")
	if not google_id_token:
		log.error("LIMA auth token exchange returned no id_token")
		raise AuthError("auth_error")

	session = _session_from_idp(sign_in_with_idp(google_id_token, config.api_key, _opener=_opener))
	if not session["uid"] or not session["idToken"]:
		raise AuthError("auth_error")

	# Environment metadata recorded alongside the profile.
	session["userAgent"] = user_agent  # real browser UA from the redirect request
	session["systemLanguage"] = _system_language()
	session["ipAddress"], session["country"] = _fetch_ip_and_country()

	_store_user(config, session, _opener=_opener)
	return session


def restore_session(config, refresh_token, _opener=None):
	"""Refresh a stored session at startup without a browser round-trip."""
	data = refresh_id_token(refresh_token, config.api_key, _opener=_opener)
	return {
		"uid": data.get("user_id", ""),
		"idToken": data.get("id_token", ""),
		"refreshToken": data.get("refresh_token", refresh_token),
		"expiresAt": time.time() + int(data.get("expires_in", "3600")) - 30,
	}
