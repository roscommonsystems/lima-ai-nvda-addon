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
	def __init__(self):
		self.calls = []

	def describe_changes(self, before, after, api_key):
		self.calls.append((before, after, api_key))
		return "described"


class RaisingVision:
	def describe_changes(self, before, after, api_key):
		raise RuntimeError("boom")


def _make(cap, vis, spoken):
	return webnarration.WebNarrator(
		cap, vis, lambda: "key", lambda t: spoken.append(t), interval=3600
	)


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
	assert vis.calls == [(b"full1", b"full2", "key")]


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


def test_vision_error_is_swallowed():
	spoken = []
	cap = FakeCapture("Site - Google Chrome", [b"t1", b"t2"], [b"full1", b"full2"], True)
	n = _make(cap, RaisingVision(), spoken)
	n._active = True
	n._check_once()  # baseline
	n._check_once()  # change -> describe_changes raises -> swallowed
	assert spoken == []
