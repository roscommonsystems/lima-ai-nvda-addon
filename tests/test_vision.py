import json
import base64
from contextlib import contextmanager

import pytest

import vision


@pytest.fixture(autouse=True)
def _endpoint_url(monkeypatch):
	"""Stand in for the NVDA plugin, which assigns vision.ENDPOINT_URL at init.

	The module deliberately ships it unset so the dev/prod backend chosen at build time
	is the only source of the URL (see firebase_config._ENVIRONMENTS).
	"""
	monkeypatch.setattr(vision, "ENDPOINT_URL", "https://backend.test/v1/chat/completions")


def test_build_payload_has_model_and_image_data_url():
	payload = vision.build_payload(b"PNGDATA", "some/model", "describe please")
	assert payload["model"] == "some/model"
	content = payload["messages"][0]["content"]
	assert content[0] == {"type": "text", "text": "describe please"}
	url = content[1]["image_url"]["url"]
	assert url.startswith("data:image/png;base64,")
	assert base64.b64decode(url.split(",", 1)[1]) == b"PNGDATA"


def test_parse_response_returns_trimmed_text():
	body = {"choices": [{"message": {"content": "  A cat.  "}}]}
	assert vision.parse_response(body) == "A cat."


def test_parse_response_raises_api_error_on_error_object():
	with pytest.raises(vision.VisionError) as exc:
		vision.parse_response({"error": {"message": "bad key"}})
	assert exc.value.code == "api_error"


def test_parse_response_raises_empty_on_blank_content():
	with pytest.raises(vision.VisionError) as exc:
		vision.parse_response({"choices": [{"message": {"content": "   "}}]})
	assert exc.value.code == "empty"


def _fake_opener(raw_bytes=None, raise_exc=None):
	@contextmanager
	def opener(request, timeout=None):
		if raise_exc is not None:
			raise raise_exc
		class _Resp:
			def read(self_inner):
				return raw_bytes
		yield _Resp()
	return opener


def test_describe_image_success_returns_text():
	raw = json.dumps({"choices": [{"message": {"content": "A login form."}}]}).encode("utf-8")
	text = vision.describe_image(b"img", "key", "m", _opener=_fake_opener(raw_bytes=raw))
	assert text == "A login form."


def test_describe_image_raises_api_error_when_endpoint_url_unset(monkeypatch):
	"""An unconfigured backend URL must fail speakably, not with a urllib TypeError."""
	monkeypatch.setattr(vision, "ENDPOINT_URL", None)
	raw = json.dumps({"choices": [{"message": {"content": "A login form."}}]}).encode("utf-8")
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"img", "key", "m", _opener=_fake_opener(raw_bytes=raw))
	assert exc.value.code == "api_error"


def test_describe_image_network_failure_raises_network_code():
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"img", "key", "m", _opener=opener)
	assert exc.value.code == "network"


def test_describe_image_http_error_raises_api_error():
	import urllib.error
	http_error = urllib.error.HTTPError("https://openrouter.ai", 401, "Unauthorized", {}, None)
	opener = _fake_opener(raise_exc=http_error)
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_image(b"img", "key", "m", _opener=opener)
	assert exc.value.code == "api_error"


def test_describe_image_logs_the_real_error_on_network_failure(caplog):
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("boom-detail"))
	with caplog.at_level("ERROR"):
		with pytest.raises(vision.VisionError):
			vision.describe_image(b"img", "key", "m", _opener=opener)
	# The real underlying error must be logged so a failure is diagnosable.
	assert any("boom-detail" in r.getMessage() for r in caplog.records)


def test_build_payload_includes_default_max_tokens():
	payload = vision.build_payload(b"img", "some/model")
	assert payload["max_tokens"] == 150


def test_build_payload_max_tokens_is_overridable():
	payload = vision.build_payload(b"img", "some/model", max_tokens=42)
	assert payload["max_tokens"] == 42


def test_describe_image_threads_max_tokens_into_request():
	captured = {}

	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))

		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

		yield _Resp()

	vision.describe_image(b"img", "key", "m", max_tokens=77, _opener=opener)
	assert captured["body"]["max_tokens"] == 77


def test_build_changes_payload_has_two_images_and_max_tokens():
	payload = vision.build_changes_payload(b"BEFORE", b"AFTER", "some/model")
	assert payload["max_tokens"] == 150
	content = payload["messages"][0]["content"]
	images = [c for c in content if c.get("type") == "image_url"]
	assert len(images) == 2
	import base64
	assert base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) == b"BEFORE"
	assert base64.b64decode(images[1]["image_url"]["url"].split(",", 1)[1]) == b"AFTER"


def test_describe_changes_success_returns_text():
	import json
	raw = json.dumps({"choices": [{"message": {"content": "A menu opened."}}]}).encode("utf-8")
	text = vision.describe_changes(b"a", b"b", "key", "m", _opener=_fake_opener(raw_bytes=raw))
	assert text == "A menu opened."


def test_describe_changes_network_failure_raises_network_code():
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	with pytest.raises(vision.VisionError) as exc:
		vision.describe_changes(b"a", b"b", "key", "m", _opener=opener)
	assert exc.value.code == "network"


def test_build_payload_includes_zdr_provider_inside_provider_object():
	payload = vision.build_payload(b"img")
	assert payload["provider"] == vision.VISION_PROVIDER
	assert payload["provider"]["zdr"] is True
	assert payload["provider"]["data_collection"] == "deny"
	assert payload["provider"]["allow_fallbacks"] is True
	assert payload["provider"]["order"] == ["Weights & Biases", "Cerebras", "Novita"]
	# ZDR must NOT be top-level (OpenRouter ignores it there).
	assert "zdr" not in payload


def test_build_changes_payload_includes_zdr_provider():
	payload = vision.build_changes_payload(b"a", b"b")
	assert payload["provider"] == vision.VISION_PROVIDER
	assert "zdr" not in payload


def test_payload_builders_default_to_gemma_model():
	assert vision.build_payload(b"img")["model"] == "google/gemma-4-31b-it"
	assert vision.build_changes_payload(b"a", b"b")["model"] == "google/gemma-4-31b-it"
	assert vision.OPENROUTER_VISION_MODEL == "google/gemma-4-31b-it"


def test_changes_prompt_without_previous_is_the_base_prompt():
	assert vision.changes_prompt() == vision.CHANGES_PROMPT
	assert vision.changes_prompt(None) == vision.CHANGES_PROMPT


def test_changes_prompt_with_previous_asks_for_only_new():
	p = vision.changes_prompt("A video is playing.")
	assert "A video is playing." in p
	assert vision.NO_CHANGE in p
	assert "new" in p.lower()


def test_describe_changes_threads_previous_into_the_prompt():
	captured = {}

	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))

		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

		yield _Resp()

	vision.describe_changes(b"a", b"b", "key", previous="A menu was open.", _opener=opener)
	text = captured["body"]["messages"][0]["content"][0]["text"]
	assert "A menu was open." in text and vision.NO_CHANGE in text
