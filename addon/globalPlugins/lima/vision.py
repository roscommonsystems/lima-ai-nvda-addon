# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: vision LLM client. Standard library only; no NVDA imports.
#
# Calls go through the LIMA backend proxy (not OpenRouter directly): the add-on sends
# its OpenAI-format body plus the user's Firebase ID token, and the backend attaches the
# per-user OpenRouter key server-side. The OpenRouter key never reaches the client.

import base64
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# Endpoint the chat body is POSTed to. Defaults to the LIMA backend proxy; the NVDA
# plugin overrides ENDPOINT_URL at init from firebase_config.LIMA_BACKEND_URL. Kept
# module-level (not imported from config) so this module stays standalone and testable.
ENDPOINT_URL = "https://lima-addon-auth-server-423416231887.us-west1.run.app/v1/chat/completions"

DEFAULT_PROMPT = (
	"Describe what is on the screen for a blind user in at most 2 to 3 short, "
	"factual sentences. Name the main elements and any important visible text. "
	"Do not narrate, interpret, tell a story, or describe moment-to-moment changes."
)

MAX_TOKENS = 150

CHANGES_PROMPT = (
	"You are assisting a blind user browsing the web. Two screenshots are given, "
	"before and after. In one or two short factual sentences, describe what changed "
	"on the page. Ignore changes likely made by the user (typing, moving the mouse, scrolling)."
)

# Sentinel the model returns when nothing meaningful is new; the caller skips speaking it.
NO_CHANGE = "NO_CHANGE"


def changes_prompt(previous=None):
	"""Prompt for a change description. When `previous` (the last thing narrated)
	is given, ask the model to describe only what is NEW, or reply with NO_CHANGE."""
	if not previous:
		return CHANGES_PROMPT
	return (
		CHANGES_PROMPT
		+ ' You have already told the user: "%s".' % previous
		+ " Describe only what is new since then, in one or two clear sentences that keep"
		+ " the useful detail of what is happening. Do not repeat what you already said."
		+ " If nothing meaningful is new, reply with exactly %s." % NO_CHANGE
	)

OPENROUTER_VISION_MODEL = "google/gemma-4-31b-it"

# Vetted, trusted ZDR-supporting providers, in priority order (Weights & Biases first).
_ZDR_PROVIDERS = ["Weights & Biases", "Cerebras", "Novita"]

# ZDR is mandatory (screenshots are sensitive): only route to Zero-Data-Retention
# endpoints. These MUST live inside the "provider" object; OpenRouter silently
# ignores a top-level zdr flag.
VISION_PROVIDER = {
	"order": _ZDR_PROVIDERS,
	"only": _ZDR_PROVIDERS,
	"zdr": True,
	"data_collection": "deny",
	"allow_fallbacks": True,
}


class VisionError(Exception):
	"""A failure with a stable code the caller maps to a spoken message.

	code is one of: "api_error", "network", "empty".
	"""

	def __init__(self, code):
		super().__init__(code)
		self.code = code


def build_payload(image_png_bytes, model=OPENROUTER_VISION_MODEL, prompt=DEFAULT_PROMPT, max_tokens=MAX_TOKENS):
	"""Build an OpenAI-format chat-completions body carrying one PNG image."""
	b64 = base64.b64encode(image_png_bytes).decode("ascii")
	data_url = "data:image/png;base64," + b64
	return {
		"model": model,
		"max_tokens": max_tokens,
		"provider": VISION_PROVIDER,
		"messages": [
			{
				"role": "user",
				"content": [
					{"type": "text", "text": prompt},
					{"type": "image_url", "image_url": {"url": data_url}},
				],
			}
		],
	}


def parse_response(body):
	"""Return the description text from a parsed JSON response dict."""
	if isinstance(body, dict) and body.get("error"):
		raise VisionError("api_error")
	try:
		text = body["choices"][0]["message"]["content"]
	except (KeyError, IndexError, TypeError):
		text = None
	if not text or not text.strip():
		raise VisionError("empty")
	return text.strip()


def _post_and_parse(payload, id_token, timeout, _opener):
	"""POST a chat payload to the LIMA backend and return the parsed description text.

	`id_token` is the caller's Firebase ID token; the backend supplies the OpenRouter
	key. Raises VisionError (speakable code) on any failure; logs the real error.
	"""
	data = json.dumps(payload).encode("utf-8")
	request = urllib.request.Request(
		ENDPOINT_URL,
		data=data,
		headers={
			"Authorization": "Bearer " + id_token,
			"Content-Type": "application/json",
		},
		method="POST",
	)
	opener = _opener or urllib.request.urlopen
	try:
		with opener(request, timeout=timeout) as response:
			raw = response.read()
	except urllib.error.HTTPError as e:
		detail = ""
		try:
			detail = e.read().decode("utf-8", "replace")[:500]
		except Exception:
			pass
		log.error("LIMA AI vision HTTP error %s: %s", getattr(e, "code", "?"), detail)
		raise VisionError("api_error") from e
	except (urllib.error.URLError, TimeoutError, OSError) as e:
		log.error("LIMA AI vision could not reach the AI service: %r", e)
		raise VisionError("network") from e
	try:
		body = json.loads(raw.decode("utf-8"))
	except ValueError as e:
		log.error("LIMA AI vision received a non-JSON response: %r", e)
		raise VisionError("empty") from e
	return parse_response(body)


def describe_image(image_png_bytes, id_token, model=OPENROUTER_VISION_MODEL, prompt=DEFAULT_PROMPT, max_tokens=MAX_TOKENS, timeout=30, _opener=None):
	"""POST one screenshot through the LIMA backend; return the description text."""
	payload = build_payload(image_png_bytes, model, prompt, max_tokens)
	return _post_and_parse(payload, id_token, timeout, _opener)


def build_changes_payload(before_png, after_png, model=OPENROUTER_VISION_MODEL, prompt=CHANGES_PROMPT, max_tokens=MAX_TOKENS):
	"""OpenAI-format body carrying two PNG images (before, after)."""
	before_url = "data:image/png;base64," + base64.b64encode(before_png).decode("ascii")
	after_url = "data:image/png;base64," + base64.b64encode(after_png).decode("ascii")
	return {
		"model": model,
		"max_tokens": max_tokens,
		"provider": VISION_PROVIDER,
		"messages": [
			{
				"role": "user",
				"content": [
					{"type": "text", "text": prompt},
					{"type": "image_url", "image_url": {"url": before_url}},
					{"type": "image_url", "image_url": {"url": after_url}},
				],
			}
		],
	}


def describe_changes(before_png, after_png, id_token, model=OPENROUTER_VISION_MODEL, previous=None, max_tokens=MAX_TOKENS, timeout=30, _opener=None):
	"""POST before/after screenshots; return a description of what changed.

	If `previous` (the last thing narrated) is given, the model is asked to
	describe only what is new since then, or to reply with NO_CHANGE.
	"""
	payload = build_changes_payload(before_png, after_png, model, changes_prompt(previous), max_tokens)
	return _post_and_parse(payload, id_token, timeout, _opener)
