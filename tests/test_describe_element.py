"""The Describe Element results window flow, run without NVDA: the plugin's own methods are loaded
from its source with NVDA's modules replaced by small fakes, as in test_announcements.py."""

import ast
from pathlib import Path
from types import SimpleNamespace

import announcements
import usage
import vision

# The methods every flow below relies on to word and speak its messages.
_MESSAGE_METHODS = ("_status_text", "_error_message", "_vision_error_message", "_speak_localized", "_announce_status")


def _load_plugin(namespace, *names):
	"""The add-on's GlobalPlugin with only the named methods, run against `namespace`."""
	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	plugin_class.body = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names + _MESSAGE_METHODS]
	for method in plugin_class.body:
		method.decorator_list = []
	plugin_class.bases = []
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = True
	plugin._searching = False
	return plugin


def _nvda(reply=None, error=None):
	"""Fakes for the NVDA, wx and AI calls these flows make, recording what they were asked to do."""
	calls = SimpleNamespace(asked=[], after=[], queued=[], spoken=[])

	def ask_vision(*args, **kwargs):
		calls.asked.append((args, kwargs))
		if error is not None:
			raise error
		return reply

	namespace = {
		"announcements": announcements,
		"usage": usage,
		"vision": SimpleNamespace(VisionError=vision.VisionError, describe_element=ask_vision, answer_element_question=ask_vision),
		"settings": SimpleNamespace(get_language=lambda: "en", get_id_token=lambda: "token"),
		"_SPEECH_LOCALES": {"tl": "fil", "vi": "vi"},
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"ui": SimpleNamespace(message=calls.spoken.append),
		"wx": SimpleNamespace(CallAfter=lambda *args: calls.after.append(args)),
		"queueHandler": SimpleNamespace(eventQueue="events", queueFunction=lambda queue, *args: calls.queued.append(args)),
	}
	return namespace, calls


def _window():
	"""A stand-in for an open results window: the capture it describes and where answers go."""
	return SimpleNamespace(image=b"png", context="Role: button", add_answer=object())


def test_a_description_opens_the_results_window_outside_nvdas_queue():
	# A modal window opened from NVDA's queue blocks NVDA's core, which then stops speaking focus
	# changes inside the window, so it has to be opened with wx.CallAfter instead.
	namespace, calls = _nvda(reply="A blue Send button.")
	plugin = _load_plugin(namespace, "_run_describe_element", "_show_element_result")
	plugin._run_describe_element(b"png", "Role: button", "token")
	assert calls.after == [(plugin._show_element_result, "A blue Send button.", b"png", "Role: button", None)]
	assert calls.queued == []
	assert not plugin._describing


def test_a_failed_description_is_spoken_and_opens_no_window():
	namespace, calls = _nvda(error=vision.VisionError("network"))
	plugin = _load_plugin(namespace, "_run_describe_element", "_show_element_result")
	plugin._run_describe_element(b"png", "Role: button", "token")
	assert calls.after == []
	assert calls.queued == [
		(plugin._speak_localized, "Could not reach the AI service. Check your connection and try again.", None, "normal", True)
	]
	assert not plugin._describing


def test_the_window_reads_the_description_once_nvda_has_announced_it():
	events = []

	class Window:
		def __init__(self, parent, description, image, context, ask):
			events.append(("open", description, image, context, ask))

		def ShowModal(self):
			events.append(("shown while marked open", plugin._result_window_open))

		def Destroy(self):
			events.append("closed")

	namespace = _nvda()[0]
	namespace.update({
		"_DescribeResultDialog": Window,
		"_DESCRIBE_READ_DELAY_MS": 500,
		"gui": SimpleNamespace(mainFrame=SimpleNamespace(prePopup=lambda: events.append("prePopup"), postPopup=lambda: events.append("postPopup"))),
		"core": SimpleNamespace(callLater=lambda delay, *args: events.append(("read after", delay, *args))),
	})
	plugin = _load_plugin(namespace, "_show_element_result", "_ask_followup")
	plugin._show_element_result("A blue button.", b"png", "Role: button", "vi")
	assert events == [
		"prePopup",
		("open", "A blue button.", b"png", "Role: button", plugin._ask_followup),
		("read after", 500, plugin._speak_localized, "A blue button.", "vi", "normal", True),
		("shown while marked open", True),
		"closed",
		"postPopup",
	]
	assert not plugin._result_window_open


def test_describe_element_while_its_window_is_open_says_so_and_opens_no_second_window():
	namespace, calls = _nvda()
	plugin = _load_plugin(namespace, "script_describeElement")
	plugin._describing = False
	plugin._result_window_open = True
	plugin.script_describeElement(None)
	assert calls.spoken == ["The element description is already open."]


def test_a_followup_is_asked_about_the_same_capture_then_added_and_spoken():
	namespace, calls = _nvda(reply="It is red.")
	plugin = _load_plugin(namespace, "_run_followup")
	window = _window()
	plugin._run_followup(window, "what colour is it?", "token")
	assert calls.asked == [((b"png", "Role: button", "what colour is it?", "token"), {"language": "en"})]
	assert calls.after == [(window.add_answer, "what colour is it?", "It is red.")]
	assert calls.queued == [(plugin._speak_localized, "It is red.", None, "normal", True)]
	assert not plugin._describing


def test_a_failed_followup_is_spoken_but_not_added_to_the_window():
	namespace, calls = _nvda(error=vision.VisionError("rate_limited", retry_after=5))
	plugin = _load_plugin(namespace, "_run_followup")
	plugin._run_followup(_window(), "what colour is it?", "token")
	assert calls.after == []
	assert calls.queued == [
		(plugin._speak_localized, "Too many requests. Please wait a moment and try again.", None, "normal", True)
	]
	assert not plugin._describing


def test_a_followup_while_lima_is_busy_says_so_and_asks_nothing():
	namespace, calls = _nvda(reply="It is red.")
	plugin = _load_plugin(namespace, "_ask_followup")
	plugin._ask_followup(_window(), "what colour is it?")
	assert calls.spoken == ["Still describing, please wait."]
	assert calls.asked == []


def test_a_followup_after_signing_out_asks_to_sign_in():
	namespace, calls = _nvda(reply="It is red.")
	namespace["settings"].get_id_token = lambda: ""
	plugin = _load_plugin(namespace, "_ask_followup")
	plugin._describing = False
	plugin._ask_followup(_window(), "what colour is it?")
	assert calls.spoken == ["Sign in with Google in LIMA AI settings to use this feature."]
	assert calls.asked == []
