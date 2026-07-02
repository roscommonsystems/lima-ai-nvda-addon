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


def select_active_geometry(point, geometries):
	"""Return the (x, y, w, h) monitor geometry whose rectangle contains `point`.

	Falls back to geometries[0] (the primary display) if none contains it.
	"""
	px, py = point
	for (x, y, w, h) in geometries:
		if x <= px < x + w and y <= py < y + h:
			return (x, y, w, h)
	return geometries[0]


def _foreground_window_center():
	"""Center point of the foreground window in virtual-desktop coordinates.

	Returns None if it cannot be determined (caller falls back to primary).
	"""
	import ctypes
	from ctypes import wintypes

	user32 = ctypes.windll.user32
	user32.GetForegroundWindow.restype = wintypes.HWND
	user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
	user32.GetWindowRect.restype = wintypes.BOOL
	hwnd = user32.GetForegroundWindow()
	if not hwnd:
		return None
	rect = wintypes.RECT()
	if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
		return None
	return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)


def capture_screen_png(max_dim=MAX_DIMENSION):
	"""Capture the active monitor and return downscaled PNG bytes.

	Requires wx and a display, so this runs inside NVDA (verified manually).
	"""
	import wx  # lazy: only available inside NVDA's runtime

	geometries = []
	for i in range(wx.Display.GetCount()):
		g = wx.Display(i).GetGeometry()
		geometries.append((g.x, g.y, g.width, g.height))

	point = _foreground_window_center()
	if point is not None and geometries:
		x, y, width, height = select_active_geometry(point, geometries)
	else:
		g = wx.Display(0).GetGeometry()
		x, y, width, height = (g.x, g.y, g.width, g.height)

	screen_dc = wx.ScreenDC()
	bitmap = wx.Bitmap(width, height)
	mem_dc = wx.MemoryDC(bitmap)
	mem_dc.Blit(0, 0, width, height, screen_dc, x, y)
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
