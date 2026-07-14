# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: screen capture via wx (bundled in NVDA).

import os
import tempfile

MAX_DIMENSION = 1280

BROWSER_IDENTIFIERS = (
	"chrome", "firefox", "edge", "safari", "opera", "brave",
	"vivaldi", "chromium", "internet explorer",
)
CHANGE_THRESHOLD = 0.03
THUMBNAIL_SIZE = (64, 48)


def is_browser_title(title):
	"""True if a window title looks like a web browser."""
	if not title:
		return False
	low = title.lower()
	return any(name in low for name in BROWSER_IDENTIFIERS)


def frames_differ(a, b, threshold=CHANGE_THRESHOLD):
	"""True if two equal-length RGB byte sequences differ by more than
	`threshold` (normalized mean absolute per-byte difference, 0..1).
	Mismatched lengths count as changed; equal empties count as unchanged."""
	if len(a) != len(b):
		return True
	if not a:
		return False
	total = 0
	for x, y in zip(a, b):
		total += abs(x - y)
	return (total / (len(a) * 255)) > threshold


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


def foreground_window_title():
	"""Title text of the foreground window, or "" if unavailable."""
	import ctypes
	from ctypes import wintypes

	user32 = ctypes.windll.user32
	user32.GetForegroundWindow.restype = wintypes.HWND
	user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
	user32.GetWindowTextLengthW.restype = ctypes.c_int
	user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
	user32.GetWindowTextW.restype = ctypes.c_int

	hwnd = user32.GetForegroundWindow()
	if not hwnd:
		return ""
	length = user32.GetWindowTextLengthW(hwnd)
	if length <= 0:
		return ""
	buf = ctypes.create_unicode_buffer(length + 1)
	user32.GetWindowTextW(hwnd, buf, length + 1)
	return buf.value


def _active_monitor_geometry():
	"""(x, y, w, h) of the monitor holding the foreground window; primary fallback."""
	import wx

	geometries = []
	for i in range(wx.Display.GetCount()):
		g = wx.Display(i).GetGeometry()
		geometries.append((g.x, g.y, g.width, g.height))
	point = _foreground_window_center()
	if point is not None and geometries:
		return select_active_geometry(point, geometries)
	g = wx.Display(0).GetGeometry()
	return (g.x, g.y, g.width, g.height)


def capture_screen_png(max_dim=MAX_DIMENSION):
	"""Capture the active monitor and return downscaled PNG bytes."""
	import wx

	x, y, width, height = _active_monitor_geometry()
	screen_dc = wx.ScreenDC()
	bitmap = wx.Bitmap(width, height)
	mem_dc = wx.MemoryDC(bitmap)
	mem_dc.Blit(0, 0, width, height, screen_dc, x, y)
	mem_dc.SelectObject(wx.NullBitmap)

	image = bitmap.ConvertToImage()
	new_w, new_h = scaled_size(width, height, max_dim)
	if (new_w, new_h) != (width, height):
		image = image.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)

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


def capture_thumbnail_rgb(size=THUMBNAIL_SIZE):
	"""Raw RGB bytes of the active monitor downscaled to `size`, for cheap
	change detection. Requires wx + a display (verified manually)."""
	import wx

	x, y, width, height = _active_monitor_geometry()
	screen_dc = wx.ScreenDC()
	bitmap = wx.Bitmap(width, height)
	mem_dc = wx.MemoryDC(bitmap)
	mem_dc.Blit(0, 0, width, height, screen_dc, x, y)
	mem_dc.SelectObject(wx.NullBitmap)

	image = bitmap.ConvertToImage().Scale(size[0], size[1], wx.IMAGE_QUALITY_NORMAL)
	return bytes(image.GetData())
