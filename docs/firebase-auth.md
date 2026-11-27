# Firebase Authentication (Google SSO) — LIMA AI NVDA Add-on

This document explains how Google sign-in is integrated into the LIMA AI NVDA
add-on, why it is built this way, how to set it up in the Firebase and Google
Cloud consoles, and how the flow works at runtime.

---

## 1. Goal

Let a user **sign in with their Google account** from inside NVDA, so the LIMA
backend (`lima-addon-auth-server`) knows who they are, and record the sign-in
(email, name, first and last sign-in, IP address, country, add-on version).

The add-on talks to Google and Firebase directly over REST to sign in. It then
tells the backend about the sign-in, and **the backend writes the profile** to
Cloud Firestore with its own service account, as `lima-auth-server` does for
LIMA desktop. Since 0.6.0 the add-on does not write to Firestore.

---

## 2. Why this approach

Firebase has **no native client SDK for a desktop Python process**. The Firebase
console only offers SDKs for iOS, Android, Web, Unity, and Flutter. NVDA add-ons
are plain Python running inside NVDA on Windows, so none of those apply. (The
Python "Firebase Admin SDK" exists but is server-side only — it verifies tokens,
it does not sign users in.)

The supported path for a desktop app is therefore:

1. **Google OAuth 2.0 "installed app" loopback flow** to get a Google ID token.
2. **Firebase Auth REST API** (`accounts:signInWithIdp`) to exchange that Google
   token for a Firebase session.
3. **`POST /sign-in` on the LIMA backend**, authorized with the Firebase ID
   token. The backend verifies the token and writes the profile.

To keep the add-on dependency-free (it is otherwise standard-library only), the
OAuth loopback is **hand-rolled** instead of pulling in `google-auth-oauthlib`.
NVDA ships a trimmed Python that omits some stdlib modules (`secrets`,
`webbrowser`, `http.server`), so the code sticks to modules that are always
present: `os.urandom` for randomness, a raw `socket` for the loopback listener,
and `os.startfile` to open the default browser. PKCE (RFC 7636) protects the
exchange.

---

## 3. Architecture at a glance

```
NVDA add-on (pure Python, stdlib only)
  1. Google OAuth loopback  ──►  Google ID token
  2. signInWithIdp (REST)   ──►  Firebase idToken + refreshToken + profile
  3. POST /sign-in          ──►  lima-addon-auth-server
                                  (Bearer: the Firebase idToken;
                                   headers: User-Agent, X-LIMA-Addon-Version,
                                   X-LIMA-Region, X-LIMA-Device)
                                          │
                                          ▼
                                  users/{uid}: email, display_name, ip_address, country,
                                  addon_version, account_created_at, last_login_at, ...

Only the backend writes to Firestore, as for LIMA desktop. The email and
name come from the verified token and the IP address from the backend's
own front end, so the add-on cannot fake them.
```

Add-ons up to 0.5.0 wrote the profile to Firestore themselves. The Firestore
rules still let them, for their profile fields only (see Part 4), until nobody
is left on those versions.

---

## 4. Files in the add-on

| File | Role |
|------|------|
| `addon/globalPlugins/lima/auth.py` | All the flow logic: PKCE loopback OAuth, code exchange, `signInWithIdp`, reporting the sign-in to the backend (`record_sign_in`), and token refresh. NVDA-free so it is unit-testable. |
| `addon/globalPlugins/lima/firebase_config.py` | The four project constants (client id/secret, Firebase API key, project id) plus `is_configured()` / `get_config()` helpers. |
| `addon/globalPlugins/lima/settings.py` | The "Google account" section in NVDA settings: **Sign in with Google** / **Sign out** button, status line, and session storage helpers. |
| `tests/test_auth.py` | Unit tests for the pure functions (PKCE, auth URL, code exchange, IdP sign-in, refresh, the backend sign-in call, the Windows region, error mapping). |

The four constants that must be filled in live in `firebase_config.py`:

```python
GOOGLE_CLIENT_ID = ""       # Google Cloud → Credentials → Desktop OAuth client
GOOGLE_CLIENT_SECRET = ""   # same client (not confidential for desktop clients)
FIREBASE_API_KEY = ""       # Firebase → Project settings → Web app → apiKey
FIREBASE_PROJECT_ID = ""    # Firebase → Project settings → Project ID
```

---

## 5. One-time console setup

> A Firebase project **is** a Google Cloud project — same project, two consoles.

### Part 1 — Firebase project + Web app → `FIREBASE_API_KEY`, `FIREBASE_PROJECT_ID`
1. Open https://console.firebase.google.com and sign in.
2. **Add project** (or select an existing one); Analytics can be disabled.
3. **Gear ⚙️ → Project settings → General**.
4. Under **Your apps**, click the **`</>` (Web)** icon.
5. Nickname it (e.g. `lima-nvda`); do **not** enable Hosting. **Register app**.
6. From the shown `firebaseConfig`, copy `apiKey` (→ `FIREBASE_API_KEY`) and
   `projectId` (→ `FIREBASE_PROJECT_ID`). Ignore the rest — the JS SDK is not used.

### Part 2 — Enable Google sign-in
1. **Build → Authentication → Get started**.
2. **Sign-in method → Google → Enable**.
3. Set a **Project support email**. **Save**.

### Part 3 — Create Firestore
1. **Build → Firestore Database → Create database**.
2. Choose a **location** (permanent). Start in **Production mode**. **Create**.

### Part 4 — Firestore security rules
The rules for LIMA's database (`lima-nvda-addon-firestore-db`) are kept, tested
and deployed from the `firestore/` folder of `lima-addon-auth-server`, not
written in the console. In outline, for `users/{uid}` and `users_dev/{uid}`:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    function profileFields() {
      return ['email', 'display_name', 'last_login_at', 'account_created_at',
              'ip_address', 'system_language', 'user_agent', 'country',
              // add-on 0.2.x
              'displayName', 'lastLoginAt', 'createdAt',
              'ipAddress', 'systemLanguage', 'userAgent'];
    }
    match /{collection}/{uid} {
      allow get: if collection in ['users', 'users_dev'] && request.auth.uid == uid;
      allow create: if collection in ['users', 'users_dev'] && request.auth.uid == uid
        && request.resource.data.keys().hasOnly(profileFields());
      allow update: if collection in ['users', 'users_dev'] && request.auth.uid == uid
        && request.resource.data.diff(resource.data).affectedKeys().hasOnly(profileFields());
      // no delete, no list
    }
  }
}
```

A user can read their own document and write its **profile fields only**. They
cannot change, add or remove the fields the server owns (`plan_tier`, the
OpenRouter key fields, the cleanup fields), and cannot delete the document.

**Do not use `allow read, write: if request.auth.uid == uid`.** That was the rule
until 27 November 2026. It let any signed-in user edit the server's fields on
their own document: for example, setting `plan_tier` made the server mint them a
new free key on every request.

These rules exist for add-ons up to 0.5.0, which write their profile to
Firestore themselves. From 0.6.0 the add-on writes nothing there. Once the
backend's `addon_version` field shows nobody is left on 0.5.0 or older, the
rules can deny clients completely, as LIMA desktop's database does.

### Part 5 — Google Cloud OAuth → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
Switch to https://console.cloud.google.com with the **same project** selected.

**5a. OAuth consent screen** (required before creating a client)
1. **APIs & Services → OAuth consent screen**.
2. User type **External → Create**.
3. Fill **App name**, **User support email**, **Developer contact email**. Save.
4. **Scopes**: none needed (email/profile/openid are default). Save.
5. **Test users**: add your own Google email so you can sign in during testing. Save.

**5b. Desktop OAuth client**
1. **APIs & Services → Credentials → + Create credentials → OAuth client ID**.
2. **Application type: Desktop app**. Name it (e.g. `lima-nvda-desktop`). **Create**.
3. Copy the **Client ID** (→ `GOOGLE_CLIENT_ID`) and **Client secret**
   (→ `GOOGLE_CLIENT_SECRET`).

### Part 6 — Fill in and build
Paste the four values into `firebase_config.py`, then rebuild with `scons`. The
**Sign in with Google** button appears in NVDA → Settings → LIMA AI.

---

## 6. How the runtime flow works

`auth.run_sign_in(config)` (called on a background thread from the settings
panel so NVDA's UI does not freeze):

1. **PKCE + state.** Generate a code verifier/challenge and a random `state`.
2. **Loopback server.** Start `HTTPServer` on `127.0.0.1:0` (a free port). The
   redirect URI becomes `http://127.0.0.1:<port>`.
3. **Open the browser.** `webbrowser.open()` sends the user to Google's consent
   page in their **default system browser** (fully accessible with their own
   NVDA setup — no embedded webview).
4. **Catch the redirect.** Google redirects back to the loopback with `?code=…&
   state=…`; the local handler captures it and shows a "you can close this tab"
   page. The `state` is verified to prevent CSRF.
5. **Exchange the code** at Google's token endpoint (with the PKCE verifier) →
   Google **id_token**.
6. **`signInWithIdp`** posts the Google id_token to Firebase → Firebase
   **idToken** + **refreshToken** + profile (`localId`, `email`, `displayName`).
7. **Record the sign-in.** `record_sign_in` POSTs an empty body to the backend's
   `/sign-in` with the Firebase idToken, the add-on's `User-Agent` and
   `X-LIMA-Addon-Version`, the Windows "Country or region" in `X-LIMA-Region`
   (`_system_region`, copied from LIMA desktop), and `X-LIMA-Device`. The backend
   writes the profile. A failure is logged and ignored: the user is signed in
   either way.
8. The session (`uid`, `email`, `displayName`, `idToken`, `refreshToken`,
   `expiresAt`) is returned; the settings panel stores the refresh token and
   profile in NVDA config and updates the UI.

**Token refresh.** Firebase ID tokens expire after one hour. `restore_session`
trades the stored refresh token for a fresh ID token via
`securetoken.googleapis.com`, so the user does not have to sign in again each
launch.

---

## 7. What the backend records

`users/{uid}` (`users_dev/{uid}` on dev), written by `lima-addon-auth-server`:

| Field | From | When |
|-------|------|------|
| `uid`, `email`, `display_name` | the verified ID token | every sign-in |
| `ip_address` | the backend's own front end | every sign-in |
| `user_agent` | `User-Agent`, e.g. `LIMA-NVDA/0.6.0 NVDA/2026.3.1` | every sign-in |
| `addon_version` | `X-LIMA-Addon-Version` | every sign-in |
| `country`, `country_source` | LemonSqueezy billing country, else `X-LIMA-Region` | when known; a region never replaces a billing country |
| `last_login_at` | the backend's clock | every sign-in |
| `account_created_at` | the backend's clock | first sign-in only |

This is the same set, with the same country rules, that `lima-auth-server`
stores for LIMA desktop. `{uid}` is the Firebase user id (`localId`), stable per
Google account per project.

**What changed in 0.6.0.** Earlier add-ons wrote `email`, `display_name`,
`last_login_at`, `account_created_at`, `ip_address`, `system_language`,
`user_agent` (the browser's) and `country` themselves. The IP address and
country came from Cloudflare's trace (`cdn-cgi/trace`). `system_language` is
no longer recorded: LIMA desktop dropped it because it was mistaken for a
country.

---

## 8. Security notes

- **The add-on does not write to Firestore.** The backend does, with its own
  service account, so nothing the add-on sends can change a user's plan or key.
  Add-ons up to 0.5.0 still write their profile directly, and the Firestore rules
  limit them to the profile fields of their own `users/{uid}` document. Matching
  the uid alone was not enough: the same document holds fields the server trusts
  (`plan_tier`, `openrouter_hash`, `key_delete_at`, `openrouter_hash_to_delete`).
- **The desktop client secret is not confidential.** Google explicitly treats
  desktop OAuth client secrets as non-secret; PKCE is the real protection. It is
  therefore acceptable to ship it inside the add-on.
- **Refresh token at rest.** It is currently stored in NVDA's config
  (plaintext). If stronger protection is wanted later, move it to the Windows
  Credential Manager (via the `keyring` package), at the cost of vendoring a
  dependency into the otherwise stdlib-only add-on.

---

## 9. Testing / publishing gotchas

- **Consent screen "Testing" mode:** while the OAuth consent screen is in
  *Testing*, only emails added as **Test users** can sign in; everyone else is
  blocked. Add your own address during development.
- **Before shipping to real users**, return to **OAuth consent screen** and
  **Publish app**. Because only the basic `email` / `profile` / `openid` scopes
  are used, publishing does **not** require Google's verification review.
- **Smoke-test end to end** once the four constants are filled in, before
  packaging — the unit tests cover the logic but not the live browser round-trip.
