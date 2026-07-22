# LIMA AI NVDA Add-on

LIMA AI is the NVDA screen-reader add-on for LIMA (Low-Vision Intelligent Machine Assistant), by Roscommon Systems. A light companion to the LIMA desktop app that brings on-demand AI screen description to NVDA users. Installs into NVDA and is distributed via the NVDA Add-on Store.

## Features

- **NVDA+Shift+D** — Describe the current screen. Captures the active monitor, sends it to a vision AI, and NVDA speaks a brief factual description.
- **NVDA+Shift+L** — Announce that the add-on is running (health check).
- **NVDA+Shift+W** — Toggle dynamic web narration. While on and a browser is focused, NVDA briefly describes changes on the page without interrupting what you're reading.

The description is deliberately a short, on-demand snapshot. Continuous narration and computer control remain exclusive to the LIMA desktop app.

## Current auth state (testing)

The add-on currently uses a **bring-your-own OpenRouter API key** setup for testing: the user pastes their OpenRouter API key into NVDA menu -> Preferences -> Settings -> LIMA AI. The model is fixed to the one the LIMA desktop app uses (`meta-llama/llama-4-maverick`), so the user does not choose it. This proves the capture -> vision -> speech pipeline end to end.

This is a testing setup, not the intended shipping experience. The planned model is: the user signs in (Firebase auth) and the AI call runs through a Roscommon backend that holds the API key server-side, so no key ever lives in this (open-source) add-on. See "Auth roadmap" below.

## Project layout

- `addon/globalPlugins/lima/__init__.py` — the global plugin (commands, orchestration, threading)
- `addon/globalPlugins/lima/capture.py` — active-monitor screen capture (wx) + PNG encode
- `addon/globalPlugins/lima/vision.py` — the AI client (currently calls OpenRouter directly; standard library only)
- `addon/globalPlugins/lima/settings.py` — NVDA settings panel + config (API key today; the model is fixed to the desktop app's)
- `buildVars.py` — add-on metadata (name, version, supported NVDA versions)
- `tests/` — unit tests (run without NVDA)

## Build

Requires Python 3.12+ and the build dependencies:

```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-build.txt
scons
```

This produces `LIMA-x.y.nvda-addon`. Install it via NVDA -> Tools -> Add-on Store -> Install from external source.

## Test

```
.venv\Scripts\python.exe -m pytest tests/ -q
```

## Auth roadmap (for the Firebase integration)

The next step is to replace the bring-your-own-key setup with sign-in plus a backend proxy:

- `settings.py` — replace the API key field with a "Sign in to LIMA" flow. Because the add-on is not a browser, login opens the system browser to a hosted Firebase login page and receives the ID token back on a localhost loopback (or a device-code flow), then stores the token in NVDA config.
- `vision.py` — change the request target from OpenRouter directly to the Roscommon backend endpoint, sending the Firebase ID token as the Authorization header instead of an API key. The backend verifies the token, enforces per-user quota / rate limits, and calls the AI provider with the server-side key.

The provider API key must never be committed to this repo; it lives only on the backend.

## License

GPL v2 (NVDA add-ons link NVDA's GPL code).
