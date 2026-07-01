import capture


def test_scaled_size_no_upscale_when_small():
	assert capture.scaled_size(800, 600, 1280) == (800, 600)


def test_scaled_size_downscales_landscape_to_max_long_side():
	assert capture.scaled_size(2560, 1440, 1280) == (1280, 720)


def test_scaled_size_downscales_portrait_to_max_long_side():
	assert capture.scaled_size(1440, 2560, 1280) == (720, 1280)


def test_scaled_size_at_boundary_is_unchanged():
	assert capture.scaled_size(1280, 1024, 1280) == (1280, 1024)
