import ast
from pathlib import Path
from string import Formatter
from types import SimpleNamespace

import pytest

import announcements
import signup


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


@pytest.mark.parametrize(
	"message, vietnamese",
	[
		("Asking LIMA.", "Đang hỏi LIMA."),
		("The element description is already open.", "Cửa sổ mô tả đối tượng đang mở."),
	],
)
def test_describe_element_window_lines_are_spoken_in_vietnamese(message, vietnamese):
	assert announcements.status_text(message, "vi", lambda text: "Other language") == vietnamese


def test_the_slow_service_message_is_spoken_in_vietnamese():
	def unexpected_fallback(text):
		pytest.fail(f"Missing Vietnamese translation for {text!r}")

	translated = announcements.status_text("The AI service is slow right now. Please try again.", "vi", unexpected_fallback)
	assert translated == "Dịch vụ AI hiện đang phản hồi chậm. Vui lòng thử lại."


def test_tagalog_credit_lines_use_the_tagalog_table():
	assert announcements.status_text("Checking credit usage.", "tl", lambda text: "Other language") == "Sinusuri ang paggamit ng credits."


def test_tagalog_falls_back_to_nvda_for_lines_it_does_not_have_yet():
	"""Only the credit lines are in Tagalog so far; other commands keep NVDA's translation."""
	assert announcements.status_text("Describing screen.", "tl", lambda text: "NVDA: " + text) == "NVDA: Describing screen."


def test_english_credit_lines_use_nvda_translation():
	assert announcements.status_text("Checking credit usage.", "en", lambda text: "NVDA: " + text) == "NVDA: Checking credit usage."


def test_first_run_welcome_names_every_default_shortcut():
	"""A new default shortcut is easy to leave out of the welcome, and new users then never hear of it."""
	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	tree = ast.parse(source)
	gestures = {
		keyword.value.value
		for node in ast.walk(tree)
		if isinstance(node, ast.Call)
		for keyword in node.keywords
		if keyword.arg == "gesture"
	}
	welcome = next(
		node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and str(node.value).startswith("Welcome to LIMA AI.")
	)
	assert gestures == {"kb:NVDA+alt+d", "kb:NVDA+alt+e", "kb:NVDA+alt+c", "kb:NVDA+alt+w", "kb:NVDA+alt+u", "kb:NVDA+alt+a"}
	for gesture in gestures:
		assert "NVDA+Alt+" + gesture[-1].upper() in welcome


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
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
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


def test_spent_credit_is_spoken_in_tagalog_with_the_reset_date():
	"""A 402 during a description says when credit returns, in the Filipino voice."""
	import usage
	import vision

	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_speak_localized", "_error_message", "_vision_error_message", "_sign_in_problem_message", "_run_describe"}
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
		"_TRANSLATED_CODES": ("credit_exhausted", "signup_not_allowed", "signup_limited"),
		"signup": signup,
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(speak=lambda sequence, priority: speech_calls.append((sequence, priority))),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=braille_calls.append)),
		"queueHandler": SimpleNamespace(eventQueue=None, queueFunction=lambda queue, fn, *args: fn(*args)),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = True
	plugin._run_describe(b"png", "token")
	expected = "Naubos mo na ang iyong LIMA credits para sa buwang ito. Magre-reset ito sa Oktubre 23."
	assert speech_calls == [([("language", "fil"), expected], "normal")]
	assert braille_calls == [expected]
	assert not plugin._describing


def test_a_signup_refusal_is_spoken_in_tagalog_with_the_wait():
	"""The backend's signup guard refusing a first description: said in Tagalog, in the Filipino
	voice, with the wait in words - not as "The AI service returned an error."."""
	import usage
	import vision

	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_speak_localized", "_error_message", "_vision_error_message", "_sign_in_problem_message", "_run_describe"}
	methods = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	for method in methods:
		method.decorator_list = []
	plugin_class.bases = []
	plugin_class.body = methods
	speech_calls, braille_calls = [], []

	def spent(png, id_token, language=None):
		raise vision.VisionError("signup_limited", retry_after=7200, reason="device")

	namespace = {
		"announcements": announcements,
		"usage": usage,
		"vision": SimpleNamespace(VisionError=vision.VisionError, describe_image=spent),
		"settings": SimpleNamespace(get_language=lambda: "tl"),
		"_SPEECH_LOCALES": {"tl": "fil", "vi": "vi"},
		"_TRANSLATED_CODES": ("credit_exhausted", "signup_not_allowed", "signup_limited"),
		"signup": signup,
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(speak=lambda sequence, priority: speech_calls.append((sequence, priority))),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=braille_calls.append)),
		"queueHandler": SimpleNamespace(eventQueue=None, queueFunction=lambda queue, fn, *args: fn(*args)),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = True
	plugin._run_describe(b"png", "token")
	expected = (
		"Masyadong maraming bagong LIMA AI account ang ginawa sa computer na ito kamakailan. "
		"Pakisubukang muli pagkalipas ng mga 2 oras, o makipag-ugnayan sa Roscommon Systems sa hello@roscommonsystems.com."
	)
	assert speech_calls == [([("language", "fil"), expected], "normal")]
	assert braille_calls == [expected]
	assert not plugin._describing

def _signup_plugin(error, uid="uid-a"):
	"""The real plugin methods for describing the screen and checking usage, with NVDA faked.
	Returns (plugin, spoken lines, sign-outs) after both meet the backend refusing `error`."""
	import usage
	import vision

	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_speak_localized", "_error_message", "_vision_error_message",
			 "_sign_in_problem_message", "_run_describe", "_run_credit_usage", "_announce_translated"}
	methods = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	for method in methods:
		method.decorator_list = []
	plugin_class.bases = []
	plugin_class.body = methods
	spoken, sign_outs = [], []

	def refuse(*args, **kwargs):
		raise vision.VisionError(error, retry_after=600, reason="ip", uid=uid)

	namespace = {
		"announcements": announcements,
		"usage": SimpleNamespace(
			fetch_credit_usage=lambda token: {"valid": False, "error": error, "reason": "ip", "retry_after": 600, "uid": uid},
			usage_text=lambda *a: "usage line", today_utc=lambda: None, limit_message=usage.limit_message,
			reset_policy=usage.reset_policy, reset_date=usage.reset_date,
		),
		"vision": SimpleNamespace(VisionError=vision.VisionError, describe_image=refuse),
		"settings": SimpleNamespace(
			get_language=lambda: "en", is_current_account=lambda uid: uid != "someone-else",
			clear_session_if_current=lambda uid: sign_outs.append(uid),
		),
		"_SPEECH_LOCALES": {"tl": "fil", "vi": "vi"},
		"_TRANSLATED_CODES": ("credit_exhausted", "signup_not_allowed", "signup_limited"),
		"signup": signup,
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(
			speak=lambda sequence, priority: spoken.append(sequence[-1]),
			speakMessage=lambda text, priority: spoken.append(text),
		),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=lambda text: None)),
		"queueHandler": SimpleNamespace(eventQueue=None, queueFunction=lambda queue, fn, *args: fn(*args)),
		"log": SimpleNamespace(exception=lambda *a: None),
		"ui": SimpleNamespace(message=spoken.append),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	plugin = namespace["GlobalPlugin"]()
	plugin._describing = True
	plugin._checking_usage = True
	plugin._run_describe(b"png", "token")
	plugin._run_credit_usage("token")
	return plugin, spoken, sign_outs


def test_a_refused_address_is_signed_out_like_lima_desktop():
	"""Left signed in, every command would repeat the refusal; the message says it happened."""
	_, spoken, sign_outs = _signup_plugin("signup_not_allowed")
	assert sign_outs == ["uid-a", "uid-a"]  # once from the description, once from the usage check
	assert len(spoken) == 2 and all("you have been signed out" in line for line in spoken)


def test_a_signup_wait_keeps_the_user_signed_in():
	"""The account is fine; it works once the wait is over."""
	_, spoken, sign_outs = _signup_plugin("signup_limited")
	assert sign_outs == []
	assert all("about 10 minutes" in line for line in spoken)

def test_a_rejected_sign_in_signs_out_and_says_how_to_sign_in_again():
	"""A 401 used to be "The AI service returned an error." Now it says what to do."""
	_, spoken, sign_outs = _signup_plugin("session_expired")
	assert sign_outs == ["uid-a", "uid-a"]
	assert len(spoken) == 2
	assert all("no longer valid" in line and "NVDA+Alt+A" in line for line in spoken)


def test_nvda_alt_a_opens_lima_ai_settings_and_nothing_else():
	"""It opens NVDA's settings at LIMA AI's page, on the GUI thread, only when pressed."""
	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	method = next(node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name == "script_openAccountSettings")
	gesture = next(k.value.value for d in method.decorator_list for k in d.keywords if k.arg == "gesture")
	method.decorator_list = []
	plugin_class.bases = []
	plugin_class.body = [method]
	calls = []
	panel, dialog, popup = object(), object(), object()
	namespace = {
		"wx": SimpleNamespace(CallAfter=lambda fn, *args: calls.append((fn, args))),
		"gui": SimpleNamespace(mainFrame=SimpleNamespace(popupSettingsDialog=popup), settingsDialogs=SimpleNamespace(NVDASettingsDialog=dialog)),
		"settings": SimpleNamespace(LimaSettingsPanel=panel),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	namespace["GlobalPlugin"]().script_openAccountSettings(None)
	assert gesture == "kb:NVDA+alt+a"
	assert calls == [(popup, (dialog, panel))]


@pytest.mark.parametrize("language", ["vi", "tl"])
def test_every_sign_in_message_names_the_shortcut_in_every_language(language):
	"""Messages that need a sign-in all end in NVDA+Alt+A, translated or not."""
	import signup
	text = lambda m: announcements.status_text(m, language, lambda x: x)
	messages = [
		signup.refusal_message("signup_not_allowed", None, None, text),
		text("Your LIMA AI sign-in is no longer valid, so you have been signed out. Press NVDA+Alt+A to sign in again."),
	]
	if language == "vi":
		messages.append(text("You are not signed in to LIMA AI. Press NVDA+Alt+A to sign in with Google."))
	for message in messages:
		assert "NVDA+Alt+A" in message
		assert not message.startswith(("LIMA AI cannot", "Your LIMA AI", "You are not")), "untranslated"


def test_a_late_failure_for_another_account_signs_nobody_out():
	"""The user switched accounts while a request for the old one was out. The new account must
	stay signed in, and they must not be told they have been signed out."""
	_, spoken, sign_outs = _signup_plugin("signup_not_allowed", uid="someone-else")
	assert sign_outs == []
	assert spoken and all("signed out" not in line for line in spoken)


def test_not_signed_in_is_spoken_in_tagalog_with_the_filipino_voice():
	"""It used to be English, in the English voice, for Tagalog users."""
	source = Path(announcements.__file__).with_name("__init__.py").read_text(encoding="utf-8")
	assert 'self._announce_status(self._error_message("signed_out"))' not in source
	plugin_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "GlobalPlugin")
	names = {"_status_text", "_speak_localized", "_error_message", "_announce_translated", "_announce_status", "_report_narration_failure"}
	plugin_class.body = [node for node in plugin_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	for method in plugin_class.body:
		method.decorator_list = []
	plugin_class.bases = []
	speech_calls = []
	namespace = {
		"announcements": announcements,
		"settings": SimpleNamespace(get_language=lambda: "tl"),
		"_SPEECH_LOCALES": {"tl": "fil", "vi": "vi"},
		"_TRANSLATED_CODES": ("credit_exhausted", "signup_not_allowed", "signup_limited", "session_expired"),
		"_": lambda text: text,
		"Spri": SimpleNamespace(NORMAL="normal"),
		"LangChangeCommand": lambda locale: ("language", locale),
		"speech": SimpleNamespace(speak=lambda sequence, priority: speech_calls.append(sequence)),
		"braille": SimpleNamespace(handler=SimpleNamespace(message=lambda text: None)),
		"ui": SimpleNamespace(message=lambda text: speech_calls.append(["default voice", text])),
	}
	exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), "plugin_commands", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	namespace["GlobalPlugin"]()._report_narration_failure("signed_out", None, True)
	assert speech_calls[0] == [
		("language", "fil"),
		"Hindi ka pa naka-sign in sa LIMA AI. Pindutin ang NVDA+Alt+A para mag-sign in gamit ang Google.",
	]


def _settings_panel(result, current_uid="uid-a"):
	"""LimaSettingsPanel's credit-usage handling from settings.py, with wx and NVDA faked.
	Returns what it did: field text, account status text, spoken lines, sign-outs, refreshes.

	There is no `gui` in the namespace on purpose: a message box would raise NameError. The
	reason is spoken and left on the page, with nothing for the user to dismiss."""
	import signup
	import usage

	source = Path(announcements.__file__).with_name("settings.py").read_text(encoding="utf-8")
	panel_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "LimaSettingsPanel")
	names = {"_show_credit_usage", "_show_sign_in_problem", "_show_account_message"}
	panel_class.body = [node for node in panel_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	panel_class.bases = []
	did = SimpleNamespace(field=[], status=[], spoken=[], sign_outs=[], refreshes=[])

	def clear_session_if_current(uid):
		if uid and uid != current_uid:
			return False
		did.sign_outs.append(uid)
		return True

	namespace = {
		"signup": signup,
		"usage": usage,
		"get_language": lambda: "en",
		"clear_session_if_current": clear_session_if_current,
		"ui": SimpleNamespace(message=did.spoken.append),
		"_": lambda text: text,
	}
	exec(compile(ast.Module(body=[panel_class], type_ignores=[]), "settings_panel", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	panel = namespace["LimaSettingsPanel"]()
	panel.creditUsage = SimpleNamespace(SetValue=did.field.append, HasFocus=lambda: False)
	panel.accountStatus = SimpleNamespace(SetLabel=did.status.append, Wrap=lambda width: None)
	panel.FromDIP = lambda value: value
	panel.Layout = lambda: None
	panel._usage_label = lambda message: message
	panel._refresh_account_ui = lambda: did.refreshes.append(1)
	panel._show_credit_usage(result)
	return did


def test_settings_a_refused_first_sign_in_is_spoken_and_left_on_the_page():
	"""Right after Sign in with Google, the panel's usage fetch is the account's first request.
	It used to show Not available and leave the user signed in. Now the reason is spoken, stays
	where "Not signed in." was, and there is no box to dismiss."""
	did = _settings_panel({"valid": False, "error": "signup_not_allowed", "uid": "uid-a"})
	assert did.sign_outs == ["uid-a"] and did.refreshes == [1]
	assert len(did.spoken) == 1 and "different Google account" in did.spoken[0]
	assert did.status == did.spoken


def test_settings_a_rejected_sign_in_is_spoken_and_left_on_the_page():
	did = _settings_panel({"valid": False, "error": "session_expired", "uid": "uid-a"})
	assert did.sign_outs == ["uid-a"] and "no longer valid" in did.spoken[0]
	assert did.status == did.spoken


def test_settings_a_signup_wait_is_spoken_and_kept_in_the_credit_usage_field():
	"""Signed in still; the field can be reached with Tab and read again."""
	did = _settings_panel({"valid": False, "error": "signup_limited", "reason": "ip", "retry_after": 600})
	assert did.sign_outs == [] and did.status == []
	assert "about 10 minutes" in did.spoken[0]
	assert did.field == did.spoken


def test_settings_a_late_failure_for_another_account_is_left_alone():
	did = _settings_panel({"valid": False, "error": "signup_not_allowed", "uid": "uid-old"})
	assert did.sign_outs == [] and did.spoken == [] and did.status == []
	assert did.field == ["Not available"]


def test_settings_an_ordinary_failure_still_reads_not_available():
	did = _settings_panel({"valid": False, "error": "unavailable"})
	assert (did.field, did.spoken, did.sign_outs) == (["Not available"], [], [])


def _sign_in_panel(configured=True):
	"""LimaSettingsPanel's sign-in failure handling from settings.py, with wx and NVDA faked.
	No `gui` in the namespace on purpose: a message box would raise NameError."""
	source = Path(announcements.__file__).with_name("settings.py").read_text(encoding="utf-8")
	panel_class = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "LimaSettingsPanel")
	names = {"_sign_in_failed", "_show_account_message", "onSignInOut"}
	keep = [node for node in panel_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
	errors = next(node for node in panel_class.body if isinstance(node, ast.Assign) and node.targets[0].id == "_SIGN_IN_ERRORS")
	panel_class.body = [errors] + keep
	panel_class.bases = []
	did = SimpleNamespace(status=[], spoken=[], enabled=[], refreshes=[])
	namespace = {
		"ui": SimpleNamespace(message=did.spoken.append),
		"_": lambda text: text,
		"is_signed_in": lambda: False,
		"firebase_config": SimpleNamespace(is_configured=lambda: configured),
	}
	exec(compile(ast.Module(body=[panel_class], type_ignores=[]), "settings_panel", "exec"), namespace)  # nosec B102  # executes AST parsed from this repo's plugin source, no external input
	panel = namespace["LimaSettingsPanel"]()
	panel.accountStatus = SimpleNamespace(SetLabel=did.status.append, Wrap=lambda width: None)
	panel.signInButton = SimpleNamespace(Enable=lambda: did.enabled.append(1))
	panel.FromDIP = lambda value: value
	panel.Layout = lambda: None
	panel._refresh_account_ui = lambda: did.refreshes.append(1)
	return panel, did


@pytest.mark.parametrize("code,expected", [
	("cancelled", "Sign-in was cancelled."),
	("timeout", "Sign-in timed out. Please try again."),
	("network", "Could not reach the sign-in service. Check your connection and try again."),
	("something new", "Sign-in failed. Please try again."),
])
def test_a_failed_sign_in_is_spoken_and_left_on_the_page_with_nothing_to_dismiss(code, expected):
	"""It used to be a message box the user had to find and press OK on."""
	panel, did = _sign_in_panel()
	panel._sign_in_failed(code)
	assert did.spoken == [expected]
	assert did.status == [expected]  # where "Not signed in." was, above the button
	assert did.enabled == [1]  # the button is ready for another try


def test_sign_in_not_set_up_is_spoken_and_left_on_the_page():
	panel, did = _sign_in_panel(configured=False)
	panel.onSignInOut(None)
	assert did.spoken == ["Google sign-in is not set up in this build of LIMA AI."]
	assert did.status == did.spoken


def test_the_settings_panel_has_no_message_boxes_left():
	source = Path(announcements.__file__).with_name("settings.py").read_text(encoding="utf-8")
	assert "messageBox" not in source
