import json
import base64
from contextlib import contextmanager

import pytest

import vision


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
