# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: vision LLM client. Standard library only; no NVDA imports.

import base64
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_PROMPT = (
	"Describe what is on the screen for a blind user in at most 2 to 3 short, "
	"factual sentences. Name the main elements and any important visible text. "
	"Do not narrate, interpret, tell a story, or describe moment-to-moment changes."
)

MAX_TOKENS = 150


class VisionError(Exception):
	"""A failure with a stable code the caller maps to a spoken message.

	code is one of: "api_error", "network", "empty".
	"""

	def __init__(self, code):
		super().__init__(code)
		self.code = code


def build_payload(image_png_bytes, model, prompt=DEFAULT_PROMPT, max_tokens=MAX_TOKENS):
	"""Build an OpenAI-format chat-completions body carrying one PNG image."""
	b64 = base64.b64encode(image_png_bytes).decode("ascii")
	data_url = "data:image/png;base64," + b64
	return {
		"model": model,
		"max_tokens": max_tokens,
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


def describe_image(image_png_bytes, api_key, model, prompt=DEFAULT_PROMPT, max_tokens=MAX_TOKENS, timeout=30, _opener=None):
	"""POST the image to OpenRouter; return the description text.

	Raises VisionError on any failure. `_opener` is injectable for tests.
	The real underlying error is logged (it surfaces in NVDA's log) while the
	caller still gets a stable, speakable code.
	"""
	payload = build_payload(image_png_bytes, model, prompt, max_tokens)
	data = json.dumps(payload).encode("utf-8")
	request = urllib.request.Request(
		OPENROUTER_URL,
		data=data,
		headers={
			"Authorization": "Bearer " + api_key,
			"Content-Type": "application/json",
			"HTTP-Referer": "https://roscommonsystems.com",
			"X-Title": "LIMA NVDA Add-on",
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
		log.error("LIMA vision HTTP error %s: %s", getattr(e, "code", "?"), detail)
		raise VisionError("api_error") from e
	except (urllib.error.URLError, TimeoutError, OSError) as e:
		log.error("LIMA vision could not reach the AI service: %r", e)
		raise VisionError("network") from e
	try:
		body = json.loads(raw.decode("utf-8"))
	except ValueError as e:
		log.error("LIMA vision received a non-JSON response: %r", e)
		raise VisionError("empty") from e
	return parse_response(body)
