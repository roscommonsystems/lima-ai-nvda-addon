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


def test_localize_appends_language_instruction_for_non_english():
	assert vision._localize("Describe.", "tl") == "Describe. Respond in Tagalog."
	assert vision._localize("Describe.", "vi") == "Describe. Respond in Vietnamese."
	assert vision._localize("Describe.", "en") == "Describe."
	assert vision._localize("Describe.", "xx") == "Describe."


@pytest.mark.parametrize("language, name", [("tl", "Tagalog"), ("vi", "Vietnamese")])
def test_describe_image_threads_language_into_prompt(language, name):
	captured = {}

	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))

		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

		yield _Resp()

	vision.describe_image(b"img", "key", language=language, _opener=opener)
	text = captured["body"]["messages"][0]["content"][0]["text"]
	assert f"Respond in {name}." in text


def test_element_prompt_includes_a11y_text():
	p = vision.element_prompt("Role: button\nName: Save")
	assert "Accessibility information:" in p
	assert "Role: button\nName: Save" in p
	assert p.startswith(vision.ELEMENT_PROMPT)


def test_describe_changes_in_vietnamese_preserves_text_and_no_change_instruction():
	captured = {}
	description = "Một hộp thoại mới xuất hiện."

	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))

		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": description}}]}, ensure_ascii=False).encode("utf-8")

		yield _Resp()

	previous = "Trang hiển thị một biểu mẫu."
	result = vision.describe_changes(b"before", b"after", "key", previous=previous, language="vi", _opener=opener)
	prompt = captured["body"]["messages"][0]["content"][0]["text"]
	assert "Respond in Vietnamese." in prompt
	assert previous in prompt
	assert "reply with exactly NO_CHANGE" in prompt
	assert result == description


def test_describe_element_success_returns_text():
	raw = json.dumps({"choices": [{"message": {"content": "A blue button."}}]}).encode("utf-8")
	text = vision.describe_element(b"img", "Role: button", "key", _opener=_fake_opener(raw_bytes=raw))
	assert text == "A blue button."


@pytest.mark.parametrize("language, name", [("tl", "Tagalog"), ("vi", "Vietnamese")])
def test_describe_element_threads_language_and_a11y_text_into_prompt(language, name):
	captured = {}
	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))
		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
		yield _Resp()
	vision.describe_element(b"img", "Role: checkbox", "key", language=language, _opener=opener)
	text = captured["body"]["messages"][0]["content"][0]["text"]
	assert "Role: checkbox" in text
	assert f"Respond in {name}." in text


def test_describe_element_raises_network_code():
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	with pytest.raises(vision.VisionError)as exc:
		vision.describe_element(b"img", "Role: button", "key", _opener=opener)
	assert exc.value.code == "network"


def test_parse_selection_reads_json_number():
	assert vision.parse_selection('{"element_number": "2", "reason": "x"}', 5) == (2, "single")


def test_parse_selection_reads_action_when_present():
	assert vision.parse_selection('{"element_number": "2", "action": "double"}', 5) == (2, "double")
	assert vision.parse_selection('{"element_number": "3", "action": "right"}', 5) == (3, "right")


def test_parse_selection_invalid_action_defaults_to_single():
	assert vision.parse_selection('{"element_number": "2", "action": "triple"}', 5) == (2, "single")


def test_parse_selection_none_when_model_declines():
	assert vision.parse_selection('{"element_number": "none", "reason": "no match"}', 5)[0] is None


def test_parse_selection_none_when_out_of_range():
	assert vision.parse_selection('{"element_number": "9"}', 5)[0] is None
	assert vision.parse_selection('{"element_number": "0"}', 5)[0] is None


def test_parse_selection_none_on_garbage_or_empty():
	assert vision.parse_selection("garbage", 5)[0] is None
	assert vision.parse_selection("", 5)[0] is None


def test_parse_selection_falls_back_to_bare_integer():
	assert vision.parse_selection("I think element 3 fits.", 5) == (3, "single")


def test_parse_selection_declined_json_ignores_number_in_reason():
	assert vision.parse_selection('{"element_number": "none", "reason": "none of the 4 match"}', 5)[0] is None


def test_select_element_success_returns_model_text():
	raw = json.dumps({"choices": [{"message": {"content": '{"element_number": "1"}'}}]}).encode("utf-8")
	out = vision.select_element(b"png", "1. Send | button | 10,20", "the send button", "key", _opener=_fake_opener(raw_bytes=raw))
	assert out == '{"element_number": "1"}'


def test_select_element_sends_description_elements_and_image():
	captured = {}

	@contextmanager
	def opener(request, timeout=None):
		captured["body"] = json.loads(request.data.decode("utf-8"))

		class _Resp:
			def read(self_inner):
				return json.dumps({"choices": [{"message": {"content": '{"element_number": "1"}'}}]}).encode("utf-8")

		yield _Resp()

	vision.select_element(b"PNGDATA", "1. Send | button | 10,20", "the send button", "key", _opener=opener)
	content = captured["body"]["messages"][0]["content"]
	text = content[0]["text"]
	assert "the send button" in text
	assert "Send | button" in text
	assert base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1]) == b"PNGDATA"


def test_select_element_network_failure_raises_network_code():
	import urllib.error
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	with pytest.raises(vision.VisionError) as exc:
		vision.select_element(b"png", "1. x | button | 0,0", "x", "key", _opener=opener)
	assert exc.value.code == "network"
