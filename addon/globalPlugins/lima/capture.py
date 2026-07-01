# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: screen capture via wx (bundled in NVDA).

import os
import tempfile

MAX_DIMENSION = 1280


def scaled_size(width, height, max_dim=MAX_DIMENSION):
	"""Return (w, h) scaled so the longest side is <= max_dim, preserving
	aspect ratio. Never upscales."""
	longest = max(width, height)
	if longest <= max_dim:
		return (width, height)
	ratio = max_dim / float(longest)
	return (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))


def capture_screen_png(max_dim=MAX_DIMENSION):
	"""Capture the whole screen and return downscaled PNG bytes.

	Requires wx and a display, so this runs inside NVDA (verified manually).
	"""
	import wx  # lazy: only available inside NVDA's runtime

	screen_dc = wx.ScreenDC()
	width, height = screen_dc.GetSize()
	bitmap = wx.Bitmap(width, height)
	mem_dc = wx.MemoryDC(bitmap)
	mem_dc.Blit(0, 0, width, height, screen_dc, 0, 0)
	mem_dc.SelectObject(wx.NullBitmap)

	image = bitmap.ConvertToImage()
	new_w, new_h = scaled_size(width, height, max_dim)
	if (new_w, new_h) != (width, height):
		image = image.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)

	# SaveFile to a real path is the most portable wx encode path across builds.
	fd, path = tempfile.mkstemp(suffix=".png")
	os.close(fd)
	try:
		image.SaveFile(path, wx.BITMAP_TYPE_PNG)
		with open(path, "rb") as f:
			return f.read()
	finally:
		try:
			os.remove(path)
		except OSError:
			pass
