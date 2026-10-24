import pytest

import webnarration


class FakeCapture:
	def __init__(self, title, thumbs, fulls, differ):
		self.title = title
		self._thumbs = list(thumbs)
		self._fulls = list(fulls)
		self._differ = differ

	def is_browser_title(self, t):
		return "chrome" in t.lower()

	def foreground_window_title(self):
		return self.title

	def capture_thumbnail_rgb(self):
		return self._thumbs.pop(0)

	def capture_screen_png(self):
		return self._fulls.pop(0)

	def frames_differ(self, a, b, threshold):
		return self._differ


class FakeVision:
	NO_CHANGE = "NO_CHANGE"

	def __init__(self, replies=None):
		self.calls = []
		self._replies = list(replies) if replies else None

	def describe_changes(self, before, after, api_key, previous=None, language="en"):
		self.calls.append((before, after, api_key, previous))
		if self._replies:
			return self._replies.pop(0)
		return "described"


class CodedError(Exception):
	"""Stands in for vision.VisionError: an exception with a speakable code."""

	def __init__(self, code):
		super().__init__(code)
		self.code = code


class RaisingVision:
	NO_CHANGE = "NO_CHANGE"

	def __init__(self, errors=None):
		# One entry per call: an exception to raise, or a description to return.
		self._script = list(errors) if errors else [RuntimeError("boom")]

	def describe_changes(self, before, after, api_key, previous=None, language="en"):
		step = self._script.pop(0) if len(self._script) > 1 else self._script[0]
		if isinstance(step, Exception):
			raise step
		return step


def _make(cap, vis, spoken, errors=None, token="key"):
	return webnarration.WebNarrator(
		cap, vis, lambda: token, lambda t: spoken.append(t), interval=3600,
		on_error=(lambda code, error, stopped: errors.append((code, stopped))) if errors is not None else (lambda *a: None),
	)


def _browser(changes):
	"""A browser window whose page changes on every check after the first."""
	return FakeCapture("Site - Google Chrome", [b"t"] * (changes + 1), [b"f"] * (changes + 1), True)


def test_toggle_flips_active():
	n = _make(FakeCapture("x", [], [], False), FakeVision(), [])
	assert n.toggle() is True
	assert n.is_active is True
	assert n.toggle() is False
	assert n.is_active is False


def test_no_narration_when_not_a_browser():
	spoken = []
	vis = FakeVision()
	n = _make(FakeCapture("Untitled - Notepad", [b"t"], [b"f"], True), vis, spoken)
	n._active = True
	n._check_once()
	assert spoken == []
	assert vis.calls == []


def test_first_browser_frame_sets_baseline_without_narrating():
	spoken = []
	vis = FakeVision()
	n = _make(FakeCapture("Site - Google Chrome", [b"thumb1"], [b"full1"], True), vis, spoken)
	n._active = True
	n._check_once()
	assert spoken == []
	assert vis.calls == []


def test_change_triggers_narration_with_before_and_after():
	spoken = []
	vis = FakeVision()
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2"], [b"full1", b"full2"], True)
	n = _make(cap, vis, spoken)
	n._active = True
	n._check_once()  # baseline: full1
	n._check_once()  # change: before=full1, after=full2
	assert spoken == ["described"]
	assert vis.calls == [(b"full1", b"full2", "key", None)]


def test_no_change_does_not_narrate():
	spoken = []
	vis = FakeVision()
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2"], [b"full1"], False)
	n = _make(cap, vis, spoken)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # thumbs differ=False -> no narration, no extra full capture
	assert spoken == []
	assert vis.calls == []


def test_stop_cancels_and_deactivates():
	n = _make(FakeCapture("x", [], [], False), FakeVision(), [])
	n.start()
	assert n.is_active is True
	assert n._timer is not None
	n.stop()
	assert n.is_active is False
	assert n._timer is None


def test_check_once_noop_when_inactive():
	spoken = []
	vis = FakeVision()
	n = _make(FakeCapture("Site - Google Chrome", [b"t"], [b"f"], True), vis, spoken)
	n._active = False
	n._check_once()
	assert spoken == []
	assert vis.calls == []


def test_a_failure_is_reported_not_spoken_as_a_description():
	spoken, errors = [], []
	n = _make(_browser(1), RaisingVision([CodedError("network")]), spoken, errors)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> describe_changes raises
	assert spoken == []
	assert errors == [("network", False)]
	assert n.is_active is True  # a network blip may pass; narration carries on


def test_the_same_failure_is_reported_once_not_every_interval():
	errors = []
	n = _make(_browser(3), RaisingVision([CodedError("network")]), [], errors)
	n._active = True
	for _ in range(4):
		n._check_once()
	assert errors == [("network", False)]


def test_a_different_failure_is_reported():
	errors = []
	n = _make(_browser(2), RaisingVision([CodedError("network"), CodedError("api_error")]), [], errors)
	n._active = True
	for _ in range(3):
		n._check_once()
	assert errors == [("network", False), ("api_error", False)]


def test_a_failure_after_a_success_is_reported_again():
	errors, spoken = [], []
	vis = RaisingVision([CodedError("network"), "A dialog opened.", CodedError("network")])
	n = _make(_browser(3), vis, spoken, errors)
	n._active = True
	for _ in range(4):
		n._check_once()
	assert spoken == ["A dialog opened."]
	assert errors == [("network", False), ("network", False)]


def test_spent_credit_stops_narration():
	"""Every later tick would get the same 402, so narration turns itself off."""
	errors = []
	n = _make(_browser(1), RaisingVision([CodedError("credit_exhausted")]), [], errors)
	n.start()
	n._check_once()  # baseline
	n._check_once()  # change -> 402
	assert errors == [("credit_exhausted", True)]
	assert n.is_active is False
	assert n._timer is None


def test_the_spent_credit_error_is_passed_on_with_its_details():
	"""The plugin needs the error itself to say when the credit resets."""
	seen = []
	error = CodedError("credit_exhausted")
	n = webnarration.WebNarrator(
		_browser(1), RaisingVision([error]), lambda: "key", lambda t: None, interval=3600,
		on_error=lambda code, err, stopped: seen.append(err),
	)
	n._active = True
	n._check_once()
	n._check_once()
	assert seen == [error]


def test_signing_out_stops_narration_without_calling_the_ai():
	errors = []
	vis = FakeVision()
	n = _make(_browser(1), vis, [], errors, token="")
	n.start()
	n._check_once()  # baseline
	n._check_once()  # change, but no token
	assert errors == [("signed_out", True)]
	assert vis.calls == []
	assert n.is_active is False


def test_a_capture_failure_is_reported_as_capture():
	class BrokenCapture(FakeCapture):
		def capture_thumbnail_rgb(self):
			raise OSError("screen locked")

	errors = []
	n = _make(BrokenCapture("Site - Google Chrome", [], [], True), FakeVision(), [], errors)
	n._active = True
	n._check_once()
	n._check_once()
	assert errors == [("capture", False)]


def test_restarting_clears_the_failure_streak():
	errors = []
	n = _make(_browser(3), RaisingVision([CodedError("network")]), [], errors)
	n._active = True
	n._check_once()
	n._check_once()
	n.stop()
	n.start()
	n._check_once()  # new baseline after start
	n._check_once()
	n.stop()
	assert errors == [("network", False), ("network", False)]


def test_skips_speaking_when_model_returns_no_change():
	spoken = []
	vis = FakeVision(replies=["NO_CHANGE"])
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2"], [b"f1", b"f2"], True)
	n = _make(cap, vis, spoken)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> model says NO_CHANGE -> not spoken
	assert spoken == []


def test_skips_exact_duplicate_description():
	spoken = []
	vis = FakeVision(replies=["A menu opened.", "A menu opened."])
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2", b"t3"], [b"f1", b"f2", b"f3"], True)
	n = _make(cap, vis, spoken)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> spoken once
	n._check_once()  # change -> same text -> skipped
	assert spoken == ["A menu opened."]


def test_passes_last_description_as_previous():
	spoken = []
	vis = FakeVision(replies=["A video is playing.", "The video stopped."])
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2", b"t3"], [b"f1", b"f2", b"f3"], True)
	n = _make(cap, vis, spoken)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # first change -> previous should be None
	n._check_once()  # second change -> previous should be the last spoken line
	assert vis.calls[0][3] is None
	assert vis.calls[1][3] == "A video is playing."
	assert spoken == ["A video is playing.", "The video stopped."]


@pytest.mark.parametrize("language", ["tl", "vi"])
def test_passes_language_to_describe_changes(language):
	captured = {}

	class LangVision:
		NO_CHANGE = "NO_CHANGE"

		def describe_changes(self, before, after, api_key, previous=None, language="en"):
			captured["language"] = language
			return "x"

	spoken = []
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2"], [b"f1", b"f2"], True)
	n = webnarration.WebNarrator(
		cap, LangVision(), lambda: "key", lambda t: spoken.append(t), get_language=lambda: language, interval=3600
	)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> describe_changes called with the language
	assert captured["language"] == language


class RateLimitedError(CodedError):
	"""Stands in for vision.VisionError("rate_limited", retry_after=...)."""

	def __init__(self, retry_after=None):
		super().__init__("rate_limited")
		self.retry_after = retry_after


class Clock:
	def __init__(self):
		self.now = 1000.0

	def __call__(self):
		return self.now


def test_the_interval_is_never_shorter_than_the_minimum():
	n = webnarration.WebNarrator(None, None, lambda: "key", lambda t: None, interval=0.2)
	assert n._interval == webnarration.WebNarrator.MIN_INTERVAL


def test_a_longer_interval_is_kept():
	n = webnarration.WebNarrator(None, None, lambda: "key", lambda t: None, interval=10.0)
	assert n._interval == 10.0


def test_rate_limited_pauses_narration_for_the_wait_the_server_asked(monkeypatch):
	clock = Clock()
	monkeypatch.setattr(webnarration.time, "monotonic", clock)
	cap = _browser(3)
	errors = []
	n = _make(cap, RaisingVision([RateLimitedError(retry_after=30), "described"]), [], errors)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> 429

	assert errors == [("rate_limited", False)]  # reported, and narration keeps running
	assert n.is_active

	clock.now += 29
	thumbs_left = len(cap._thumbs)
	n._check_once()  # still inside the wait: nothing captured, nothing sent
	assert len(cap._thumbs) == thumbs_left

	clock.now += 2
	n._check_once()  # wait over: checks the screen again
	assert len(cap._thumbs) == thumbs_left - 1


def test_rate_limited_without_a_wait_pauses_for_one_interval(monkeypatch):
	clock = Clock()
	monkeypatch.setattr(webnarration.time, "monotonic", clock)
	n = _make(_browser(2), RaisingVision([RateLimitedError()]), [], [])
	n._active = True
	n._check_once()
	n._check_once()
	assert n._paused_until == clock.now + 3600  # _make's interval


def test_restarting_clears_a_rate_limit_pause(monkeypatch):
	clock = Clock()
	monkeypatch.setattr(webnarration.time, "monotonic", clock)
	n = _make(_browser(2), RaisingVision([RateLimitedError(retry_after=30)]), [], [])
	n._active = True
	n._check_once()
	n._check_once()
	n.start()
	n.stop()
	assert n._paused_until == 0.0
