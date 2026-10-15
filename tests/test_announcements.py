import ast
from pathlib import Path
from string import Formatter
from types import SimpleNamespace

import pytest

import announcements


CLICK_MESSAGES = [
	"Search cancelled.",
	"Finding {desc}.",
	"I could not find anything to click here.",
	"I could not find {desc}.",
	"Clicked {name}.",
	"Double-clicked {name}.",
	"Right-clicked {name}.",
	"The click could not be performed. Please try again.",
]


@pytest.mark.parametrize("message", CLICK_MESSAGES)
def test_vietnamese_click_announcements_preserve_format_fields(message):
	def unexpected_fallback(text):
		pytest.fail(f"Missing Vietnamese translation for {text!r}")

	translated = announcements.status_text(message, "vi", unexpected_fallback)
	assert translated.strip()
	assert translated != message
	formatter = Formatter()
	original_fields = [field for _, field, _, _ in formatter.parse(message) if field is not None]
	translated_fields = [field for _, field, _, _ in formatter.parse(translated) if field is not None]
	assert sorted(translated_fields) == sorted(original_fields)
	values = {"desc": "nút Gửi", "name": "Tải xuống"}
	formatted = translated.format(**values)
	for field in original_fields:
		assert values[field] in formatted


@pytest.mark.parametrize("message", CLICK_MESSAGES)
@pytest.mark.parametrize("language", ["en", "tl", "unknown"])
def test_click_announcements_keep_interface_translation_for_other_languages(message, language):
	assert announcements.status_text(message, language, lambda text: "Translated: " + text) == "Translated: " + message


def test_unknown_vietnamese_message_uses_interface_translation():
	assert announcements.status_text("Unknown status.", "vi", lambda text: "Fallback: " + text) == "Fallback: Unknown status."


@pytest.mark.parametrize("language", ["en", "tl", "unknown"])
def test_other_languages_keep_nvda_interface_translation(language):
	assert announcements.status_text("Describing screen.", language, lambda text: "Translated: " + text) == "Translated: Describing screen."


def test_vietnamese_status_ignores_nvda_interface_language():
	assert announcements.status_text("Describing screen.", "vi", lambda text: "Other language") == "Đang mô tả màn hình."


def test_command_start_and_capture_error_use_vietnamese_speech_and_braille():
	# Load the real command methods without requiring a running NVDA process.
	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_announce_status", "_speak_localized", "_error_message", "script_describeScreen"}
	methods = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	for method in methods:
		method.decorator_list = []
	plugin_class.bases = []
	plugin_class.body = methods
	speech_calls, braille_calls, ui_calls = [], [], []

	def fail_capture():
		raise RuntimeError("capture failed")

	namespace = {
		"announcements": announcements,
		"settings": SimpleNamespace(get_language=lambda: "vi", get_id_token=lambda: "token"),
		"_": lambda text: "Interface translation: " + text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(speak=lambda sequence, priority: speech_calls.append((sequence, priority))),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=braille_calls.append)),
		"ui": SimpleNamespace(message=ui_calls.append),
		"capture": SimpleNamespace(capture_screen_png=fail_capture),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = False
	plugin._searching = False
	plugin.script_describeScreen(None)
	assert speech_calls == [
		([("language", "vi"), "Đang mô tả màn hình."], "normal"),
		([("language", "vi"), "Không thể chụp màn hình hoặc đối tượng."], "normal"),
	]
	assert braille_calls == ["Đang mô tả màn hình.", "Không thể chụp màn hình hoặc đối tượng."]
	assert not ui_calls
	assert not plugin._describing
