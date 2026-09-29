import capture


def test_scaled_size_no_upscale_when_small():
	assert capture.scaled_size(800, 600, 1280) == (800, 600)


def test_scaled_size_downscales_landscape_to_max_long_side():
	assert capture.scaled_size(2560, 1440, 1280) == (1280, 720)


def test_scaled_size_downscales_portrait_to_max_long_side():
	assert capture.scaled_size(1440, 2560, 1280) == (720, 1280)


def test_scaled_size_at_boundary_is_unchanged():
	assert capture.scaled_size(1280, 1024, 1280) == (1280, 1024)


def test_select_active_geometry_point_in_second_monitor():
	geometries = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
	assert capture.select_active_geometry((2000, 500), geometries) == (1920, 0, 1920, 1080)


def test_select_active_geometry_point_in_first_monitor():
	geometries = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
	assert capture.select_active_geometry((100, 100), geometries) == (0, 0, 1920, 1080)


def test_select_active_geometry_falls_back_to_primary_when_outside_all():
	geometries = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
	assert capture.select_active_geometry((-500, -500), geometries) == (0, 0, 1920, 1080)


def test_select_active_geometry_single_monitor():
	geometries = [(0, 0, 1920, 1080)]
	assert capture.select_active_geometry((100, 100), geometries) == (0, 0, 1920, 1080)


def test_select_active_geometry_boundary_belongs_to_second_monitor():
	# Half-open interval: the seam pixel (1920,0) belongs to the second monitor.
	geometries = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
	assert capture.select_active_geometry((1920, 0), geometries) == (1920, 0, 1920, 1080)


def test_is_browser_title_true_for_browsers():
	assert capture.is_browser_title("Downloads - Google Chrome")
	assert capture.is_browser_title("Mozilla Firefox")
	assert capture.is_browser_title("Qt | Cross-platform software design - Microsoft Edge")


def test_is_browser_title_false_for_non_browsers_and_empty():
	assert not capture.is_browser_title("Untitled - Notepad")
	assert not capture.is_browser_title("")


def test_frames_differ_identical_is_false():
	a = bytes([100]) * 300
	assert capture.frames_differ(a, a, 0.03) is False


def test_frames_differ_large_change_is_true():
	a = bytes([0]) * 300
	b = bytes([255]) * 300
	assert capture.frames_differ(a, b, 0.03) is True


def test_frames_differ_small_change_below_threshold_is_false():
	a = bytearray([100]) * 300
	b = bytearray([100]) * 300
	b[0] = 110  # tiny change
	assert capture.frames_differ(bytes(a), bytes(b), 0.03) is False


def test_frames_differ_mismatched_length_is_true():
	assert capture.frames_differ(bytes([0]) * 10, bytes([0]) * 20, 0.03) is True

V100 =  100
V50 =  50
V30 =  30
V94 =  94
V62 =  62
V42 =  42
V6 =  6
V0 =  0
V1920 =  1920
V1080 =  1080
V56 =  56
V5000 =  5000
V10 =  10
V20 =  20


def T4(a,b,c,d):
	return (a,b,c,d)


R1 = T4(V100,V100,V50,V30)
R2 = T4(V94,V94,V62,V42)
R3 = T4(V0 - V50,V0 - V50,V100,V100)
R4 = T4(V5000,V5000,V10,V10)
R5 = T4(V10,V10,V0,V20)
R8 = T4(V0,V0,V56,V56)
B0 = T4(V0,V0,V1920,V1080)
R7 = T4(V5000,V5000,V50,V50)


def test_expand_and_clamp_adds_padding_and_clips_to_bounds():
	assert capture._expand_and_clamp(R1,V6,B0) == R2


def test_expand_and_clamp_clips_partially_visible_rect():
	assert capture._expand_and_clamp(R3,V6,B0) == R8


def test_expand_and_clamp_fully_outside_returns_none():
	assert capture._expand_and_clamp(R4,V6,B0) is None


def test_expand_and_clamp_zero_sized_rect_is_none():
	assert capture._expand_and_clamp(R5,V6,B0) is None


def test_capture_element_png_returns_none_when_off_active_monitor(monkeypatch):
	monkeypatch.setattr(capture, "_active_monitor_geometry", lambda: (V0,V0,V1920,V1080))
	assert capture.capture_element_png(R7) is None
