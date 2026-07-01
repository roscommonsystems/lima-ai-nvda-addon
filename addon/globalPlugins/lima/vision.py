# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: vision LLM client. Standard library only; no NVDA imports.

import base64
import json
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_PROMPT = (
	"You are assisting a blind user. Describe what is currently shown on the "
	"screen in 2 to 4 short sentences. Be concise and factual. Focus on the "
	"main content, layout, and any important visible text."
)


class VisionError(Exception):
	"""A failure with a stable code the caller maps to a spoken message.

	code is one of: "api_error", "network", "empty".
	"""

	def __init__(self, code):
		super().__init__(code)
		self.code = code


def build_payload(image_png_bytes, model, prompt=DEFAULT_PROMPT):
	"""Build an OpenAI-format chat-completions body carrying one PNG image."""
	b64 = base64.b64encode(image_png_bytes).decode("ascii")
	data_url = "data:image/png;base64," + b64
	return {
		"model": model,
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


def describe_image(image_png_bytes, api_key, model, prompt=DEFAULT_PROMPT, timeout=20, _opener=None):
	"""POST the image to OpenRouter; return the description text.

	Raises VisionError on any failure. `_opener` is injectable for tests.
	"""
	payload = build_payload(image_png_bytes, model, prompt)
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
	except urllib.error.HTTPError:
		raise VisionError("api_error")
	except (urllib.error.URLError, TimeoutError, OSError):
		raise VisionError("network")
	try:
		body = json.loads(raw.decode("utf-8"))
	except ValueError:
		raise VisionError("empty")
	return parse_response(body)
