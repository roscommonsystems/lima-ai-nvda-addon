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
	assert capture.is_browser_title("Qt | Cross-platform software design - Microsoft​ Edge")


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
