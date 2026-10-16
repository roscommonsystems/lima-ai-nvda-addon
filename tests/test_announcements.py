import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import announcements


@pytest.mark.parametrize("language", ["en", "tl", "unknown"])
def test_other_languages_keep_nvda_interface_translation(language):
	assert announcements.status_text("Describing screen.", language, lambda text: "Translated: " + text) == "Translated: Describing screen."


def test_vietnamese_status_ignores_nvda_interface_language():
	assert announcements.status_text("Describing screen.", "vi", lambda text: "Other language") == "Đang mô tả màn hình."


def test_tagalog_credit_lines_use_the_tagalog_table():
	assert announcements.status_text("Checking credit usage.", "tl", lambda text: "Other language") == "Sinusuri ang paggamit ng credits."


def test_tagalog_falls_back_to_nvda_for_lines_it_does_not_have_yet():
	"""Only the credit lines are in Tagalog so far; other commands keep NVDA's translation."""
	assert announcements.status_text("Describing screen.", "tl", lambda text: "NVDA: " + text) == "NVDA: Describing screen."


def test_english_credit_lines_use_nvda_translation():
	assert announcements.status_text("Checking credit usage.", "en", lambda text: "NVDA: " + text) == "NVDA: Checking credit usage."


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
		([("language", "vi"), "Không thể chụp màn hình hoặc phần tử."], "normal"),
	]
	assert braille_calls == ["Đang mô tả màn hình.", "Không thể chụp màn hình hoặc phần tử."]
	assert not ui_calls
	assert not plugin._describing


def test_spent_credit_is_spoken_in_tagalog_with_the_reset_date():
	"""A 402 during a description says when credit returns, in the Filipino voice."""
	import usage
	import vision

	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_speak_localized", "_error_message", "_vision_error_message", "_run_describe"}
	methods = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	for method in methods:
		method.decorator_list = []
	plugin_class.bases = []
	plugin_class.body = methods
	speech_calls, braille_calls = [], []

	def spent(png, id_token, language=None):
		raise vision.VisionError("credit_exhausted", resets="monthly", resets_at="2026-10-23")

	namespace = {
		"announcements": announcements,
		"usage": usage,
		"vision": SimpleNamespace(VisionError=vision.VisionError, describe_image=spent),
		"settings": SimpleNamespace(get_language=lambda: "tl"),
		"_SPEECH_LOCALES": {"tl": "fil", "vi": "vi"},
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(speak=lambda sequence, priority: speech_calls.append((sequence, priority))),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=braille_calls.append)),
		"queueHandler": SimpleNamespace(eventQueue=None, queueFunction=lambda queue, fn, *args: fn(*args)),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = True
	plugin._run_describe(b"png", "token")
	expected = "Naubos mo na ang iyong LIMA credits para sa buwang ito. Magre-reset ito sa Oktubre 23."
	assert speech_calls == [([("language", "fil"), expected], "normal")]
	assert braille_calls == [expected]
	assert not plugin._describing
