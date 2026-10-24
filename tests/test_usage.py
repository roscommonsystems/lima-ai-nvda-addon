import datetime
import json
import urllib.error
from contextlib import contextmanager

import pytest

import announcements
import usage


TODAY = datetime.date(2026, 10, 16)


@pytest.fixture(autouse=True)
def _endpoint(monkeypatch):
	monkeypatch.setattr(usage, "ENDPOINT_URL", "https://backend.example/usage")


def _fake_opener(raw_bytes=None, raise_exc=None, seen=None):
	@contextmanager
	def opener(request, timeout):
		if seen is not None:
			seen.append(request)
		if raise_exc is not None:
			raise raise_exc

		class _Resp:
			def read(self):
				return raw_bytes

		yield _Resp()

	return opener


def _ok(body):
	return _fake_opener(raw_bytes=json.dumps(body).encode("utf-8"))


def _http_error(code, body=b""):
	import io
	return urllib.error.HTTPError("https://backend.example/usage", code, "err", {}, io.BytesIO(body))


def _text(language):
	return lambda message: announcements.status_text(message, language, lambda m: m)


# --- fetch_credit_usage ------------------------------------------------------------------

def test_fetch_returns_the_percentage_and_reset():
	result = usage.fetch_credit_usage("tok", _opener=_ok({
		"usage_percent": 34, "plan_tier": "go", "resets": "monthly", "resets_at": "2026-10-20",
	}))
	assert result == {
		"valid": True,
		"usage_percent": 34,
		"plan_tier": "go",
		"resets": "monthly",
		"resets_at": datetime.date(2026, 10, 20),
	}


def test_fetch_posts_the_id_token_as_a_bearer_token():
	seen = []
	usage.fetch_credit_usage("tok-123", _opener=_fake_opener(raw_bytes=b'{"usage_percent": 1}', seen=seen))
	request = seen[0]
	assert request.get_method() == "POST"
	assert request.full_url == "https://backend.example/usage"
	assert request.get_header("Authorization") == "Bearer tok-123"


def test_fetch_without_a_token_is_signed_out():
	assert usage.fetch_credit_usage("", _opener=_ok({})) == {"valid": False, "error": "signed_out"}


def test_fetch_without_an_endpoint_is_unavailable(monkeypatch):
	monkeypatch.setattr(usage, "ENDPOINT_URL", None)
	assert usage.fetch_credit_usage("tok", _opener=_ok({}))["error"] == "unavailable"


@pytest.mark.parametrize("status", [401, 403, 404, 500, 502])
def test_fetch_http_errors_are_unavailable(status):
	opener = _fake_opener(raise_exc=_http_error(status, b'{"message": "no_key_provisioned"}'))
	assert usage.fetch_credit_usage("tok", _opener=opener) == {"valid": False, "error": "unavailable"}


def test_fetch_rate_limited_is_its_own_code_but_still_reads_not_available():
	opener = _fake_opener(raise_exc=_http_error(429, b'{"message": "rate_limited", "retry_after": 30}'))
	result = usage.fetch_credit_usage("tok", _opener=opener)
	assert result == {"valid": False, "error": "rate_limited"}
	assert usage.usage_text(result, TODAY, lambda m: m, "en") == "Credits used: Not available"


def test_fetch_network_failure_is_network():
	opener = _fake_opener(raise_exc=urllib.error.URLError("down"))
	assert usage.fetch_credit_usage("tok", _opener=opener) == {"valid": False, "error": "network"}


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'{"usage_percent": "34"}', b'{"usage_percent": true}'])
def test_fetch_malformed_answers_are_unavailable(raw):
	assert usage.fetch_credit_usage("tok", _opener=_fake_opener(raw_bytes=raw))["error"] == "unavailable"


def test_fetch_null_percent_is_kept_as_none():
	result = usage.fetch_credit_usage("tok", _opener=_ok({"usage_percent": None, "plan_tier": "go"}))
	assert result["valid"] is True
	assert result["usage_percent"] is None


def test_fetch_drops_an_unknown_policy_and_a_bad_date():
	result = usage.fetch_credit_usage("tok", _opener=_ok({
		"usage_percent": 5, "resets": "weekly", "resets_at": "next tuesday",
	}))
	assert result["resets"] is None
	assert result["resets_at"] is None


# --- the line the user hears ---------------------------------------------------------------

def _usage(percent, resets="monthly", resets_at=None):
	return {"valid": True, "usage_percent": percent, "plan_tier": "go", "resets": resets, "resets_at": resets_at}


@pytest.mark.parametrize("days,phrase", [
	(1, "resets tomorrow"),
	(2, "resets in 2 days"),
	(7, "resets in 7 days"),
	(8, "resets October 24"),
])
def test_reset_phrase_boundaries(days, phrase):
	resets_at = TODAY + datetime.timedelta(days=days)
	assert usage.reset_phrase(resets_at, TODAY, _text("en"), "en") == phrase


def test_a_reset_date_at_or_before_today_reads_as_a_date():
	assert usage.reset_phrase(TODAY, TODAY, _text("en"), "en") == "resets October 16"


def test_monthly_with_a_date():
	line = usage.usage_text(_usage(34, resets_at=TODAY + datetime.timedelta(days=4)), TODAY, _text("en"), "en")
	assert line == "Credits used this month: 34% — resets in 4 days"


def test_monthly_without_a_date():
	assert usage.usage_text(_usage(34), TODAY, _text("en"), "en") == "Credits used this month: 34%"


def test_a_key_that_never_resets():
	line = usage.usage_text(_usage(34, resets="never"), TODAY, _text("en"), "en")
	assert line == "Credits used: 34% (one-time credit — does not reset)"


def test_an_unknown_policy_still_shows_the_percentage():
	assert usage.usage_text(_usage(34, resets=None), TODAY, _text("en"), "en") == "Credits used: 34%"


@pytest.mark.parametrize("result", [
	None,
	{"valid": False, "error": "network"},
	{"valid": False, "error": "unavailable"},
	{"valid": True, "usage_percent": None, "resets": "monthly", "resets_at": None},
])
def test_no_number_is_not_available_never_zero(result):
	assert usage.usage_text(result, TODAY, _text("en"), "en") == "Credits used: Not available"


def test_pending():
	assert usage.usage_text(None, TODAY, _text("en"), "en", pending=True) == "Credits used: checking…"


def test_zero_percent_is_shown_as_zero():
	assert usage.usage_text(_usage(0), TODAY, _text("en"), "en") == "Credits used this month: 0%"


# --- the settings field, which follows the "Credit usage:" label --------------------------

@pytest.mark.parametrize("result,expected", [
	(_usage(0, resets_at=TODAY + datetime.timedelta(days=5)), "0% used this month — resets in 5 days"),
	(_usage(34), "34% used this month"),
	(_usage(34, resets="never"), "34% used (one-time credit — does not reset)"),
	(_usage(34, resets=None), "34% used"),
	(None, "Not available"),
])
def test_the_field_starts_with_the_figure(result, expected):
	assert usage.usage_text(result, TODAY, _text("en"), "en", field=True) == expected


def test_the_field_pending():
	assert usage.usage_text(None, TODAY, _text("en"), "en", pending=True, field=True) == "Checking…"


@pytest.mark.parametrize("language", ["en", "tl", "vi"])
def test_the_field_never_repeats_its_label(language):
	"""Label + field must not read "Credit usage: Credits used this month: ...". """
	text = _text(language)
	label = text("Credit usage:")
	field = usage.usage_text(_usage(34, resets_at=TODAY + datetime.timedelta(days=4)), TODAY, text, language, field=True)
	spoken_prefix = text("Credits used this month: {percent}%").split("{percent}")[0].strip()
	assert spoken_prefix not in field
	assert field[0].isdigit() or language == "vi"  # vi puts the verb first: "Đã dùng 34%..."
	assert label.rstrip(":") not in field


@pytest.mark.parametrize("language", ["en", "tl", "vi"])
def test_the_sizing_samples_are_the_widest_lines(language):
	"""The panel sizes the field from these, so each must be at least as long as any real
	line: 100%, worded as a date (not "in N days"), the longest month."""
	text = _text(language)
	samples = usage.field_samples(text, language)
	widest = max(samples, key=len)
	for days in (1, 4, 20):
		for percent in (0, 34, 99, 100):
			real = usage.usage_text(_usage(percent, resets_at=TODAY + datetime.timedelta(days=days)), TODAY, text, language, field=True)
			assert len(real) <= len(widest), real
	assert usage.usage_text(_usage(100, resets="never"), TODAY, text, language, field=True) in samples
	assert all("100%" in s for s in samples[:4])


def test_the_english_sizing_sample():
	assert usage.field_samples(_text("en"), "en")[0] == "100% used this month — resets September 30"


@pytest.mark.parametrize("language,expected", [
	("tl", "34% ang nagamit ngayong buwan — magre-reset sa loob ng 4 araw"),
	("vi", "Đã dùng 34% trong tháng này — đặt lại sau 4 ngày"),
])
def test_the_field_in_each_language(language, expected):
	line = usage.usage_text(_usage(34, resets_at=TODAY + datetime.timedelta(days=4)), TODAY, _text(language), language, field=True)
	assert line == expected


# --- languages -----------------------------------------------------------------------------

@pytest.mark.parametrize("language,expected", [
	("en", "Credits used this month: 34% — resets October 30"),
	("tl", "Nagamit na credits ngayong buwan: 34% — magre-reset sa Oktubre 30"),
	("vi", "Tín dụng đã dùng trong tháng này: 34% — đặt lại vào ngày 30 tháng 10"),
])
def test_the_line_in_each_language(language, expected):
	line = usage.usage_text(_usage(34, resets_at=datetime.date(2026, 10, 30)), TODAY, _text(language), language)
	assert line == expected


@pytest.mark.parametrize("language,expected", [
	("en", "Credits used this month: 34% — resets in 3 days"),
	("tl", "Nagamit na credits ngayong buwan: 34% — magre-reset sa loob ng 3 araw"),
	("vi", "Tín dụng đã dùng trong tháng này: 34% — đặt lại sau 3 ngày"),
])
def test_soon_in_each_language(language, expected):
	line = usage.usage_text(_usage(34, resets_at=TODAY + datetime.timedelta(days=3)), TODAY, _text(language), language)
	assert line == expected


@pytest.mark.parametrize("language,expected", [
	("en", "Credits used: Not available"),
	("tl", "Nagamit na credits: Hindi available"),
	("vi", "Tín dụng đã dùng: Không có thông tin"),
])
def test_not_available_in_each_language(language, expected):
	assert usage.usage_text(None, TODAY, _text(language), language) == expected


@pytest.mark.parametrize("language", ["tl", "vi"])
def test_every_credit_line_is_translated_in_tagalog_and_vietnamese(language):
	"""A credit line missing from either table would be spoken in English with that
	language's voice."""
	english = [
		"Credit usage:",
		"Credits used this month: {percent}%",
		"Credits used: {percent}%",
		"Credits used: {percent}% (one-time credit — does not reset)",
		"Credits used: Not available",
		"Credits used: checking…",
		"resets tomorrow",
		"resets in {n} days",
		"resets {date}",
		"Checking credit usage.",
		"You've used all your LIMA credit for this month.",
		"It resets on {date}.",
		"It resets next month.",
		"Checking…",
		"Not available",
		"{percent}% used this month",
		"{percent}% used (one-time credit — does not reset)",
		"{percent}% used",
	]
	table = {"tl": announcements.TAGALOG, "vi": announcements.VIETNAMESE}[language]
	for message in english:
		assert message in table, message
		# Placeholders survive translation.
		for placeholder in ("{percent}", "{n}", "{date}"):
			assert (placeholder in message) == (placeholder in table[message]), message


@pytest.mark.parametrize("language,date", [
	("en", "October 23"),
	("tl", "Oktubre 23"),
	("vi", "ngày 23 tháng 10"),
])
def test_format_date(language, date):
	assert usage.format_date(datetime.date(2026, 10, 23), language) == date


# --- the out-of-credit message --------------------------------------------------------------

def test_limit_message_with_a_date():
	assert usage.limit_message("monthly", datetime.date(2026, 10, 23), _text("en"), "en") == (
		"You've used all your LIMA credit for this month. It resets on October 23."
	)


def test_limit_message_without_a_date():
	assert usage.limit_message("monthly", None, _text("en"), "en") == (
		"You've used all your LIMA credit for this month. It resets next month."
	)


def test_limit_message_from_an_older_server_with_no_reset_fields():
	assert usage.limit_message(None, None, _text("en"), "en") == (
		"You've used all your LIMA credit for this month. It resets next month."
	)


def test_limit_message_for_a_key_that_never_resets_promises_nothing():
	assert usage.limit_message("never", datetime.date(2026, 10, 23), _text("en"), "en") == (
		"You've used all your LIMA credit for this month."
	)


@pytest.mark.parametrize("language,expected", [
	("tl", "Naubos mo na ang iyong LIMA credits para sa buwang ito. Magre-reset ito sa Oktubre 23."),
	("vi", "Bạn đã dùng hết tín dụng LIMA của tháng này. Tín dụng sẽ được đặt lại vào ngày 23 tháng 10."),
])
def test_limit_message_in_each_language(language, expected):
	assert usage.limit_message("monthly", datetime.date(2026, 10, 23), _text(language), language) == expected
