# Firebase Authentication (Google SSO) — LIMA AI NVDA Add-on

This document explains how Google sign-in is integrated into the LIMA AI NVDA
add-on, why it is built this way, how to set it up in the Firebase and Google
Cloud consoles, and how the flow works at runtime.

---

## 1. Goal

Let a user **sign in with their Google account** from inside NVDA, and **store
their profile** (email, display name, first-login and last-login timestamps) in
**Cloud Firestore** — sign-in is purely for identifying the user and recording their details.

Because there is no enforcement, the whole thing is **client-side**: the add-on
talks to Google and Firebase directly over REST. No backend server is required.

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
3. **Firestore REST API** to write the user document, authorized with the
   Firebase ID token and protected by Firestore security rules.

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
  3. Firestore REST write   ──►  users/{uid}: email, displayName, createdAt, lastLoginAt
                                  (authorized with the Firebase idToken)

No backend. Firestore security rules enforce that a user can only
read/write their own users/{uid} document.
```

---

## 4. Files in the add-on

| File | Role |
|------|------|
| `addon/globalPlugins/lima/auth.py` | All the flow logic: PKCE loopback OAuth, code exchange, `signInWithIdp`, Firestore upsert, and token refresh. NVDA-free so it is unit-testable. |
| `addon/globalPlugins/lima/firebase_config.py` | The four project constants (client id/secret, Firebase API key, project id) plus `is_configured()` / `get_config()` helpers. |
| `addon/globalPlugins/lima/settings.py` | The "Google account" section in NVDA settings: **Sign in with Google** / **Sign out** button, status line, and session storage helpers. |
| `tests/test_auth.py` | Unit tests for the pure functions (PKCE, auth URL, code exchange, IdP sign-in, refresh, Firestore masks, error mapping). |

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

### Part 4 — Firestore security rule
In **Firestore → Rules**, publish:
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{uid} {
      allow read, write: if request.auth.uid == uid;
    }
  }
}
```
This is what makes direct client writes safe: each user can only touch their own
`users/{uid}` document.

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
7. **Firestore write.** `get_user_document` checks whether `users/{uid}` exists;
   `save_user_login` then upserts `email`, `displayName`, `lastLoginAt` always,
   and `createdAt` only on the first sign-in. An `updateMask` is used so only
   these fields are touched and any other fields on the doc are preserved.
8. The session (`uid`, `email`, `displayName`, `idToken`, `refreshToken`,
   `expiresAt`) is returned; the settings panel stores the refresh token and
   profile in NVDA config and updates the UI.

**Token refresh.** Firebase ID tokens expire after one hour. `restore_session`
trades the stored refresh token for a fresh ID token via
`securetoken.googleapis.com`, so the user does not have to sign in again each
launch.

---

## 7. Firestore document shape

`users/{uid}`:

| Field | Type | When written |
|-------|------|--------------|
| `email` | string | every sign-in |
| `displayName` | string | every sign-in |
| `createdAt` | timestamp | first sign-in only |
| `lastLoginAt` | timestamp | every sign-in |

`{uid}` is the Firebase user id (`localId`), stable per Google account per
project.

---

## 8. Security notes

- **Direct client writes are safe** only because of the Firestore rule pinning
  writes to `request.auth.uid == uid`. Do not loosen it.
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
