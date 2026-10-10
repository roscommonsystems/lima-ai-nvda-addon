# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: perform a mouse click at a screen point via NVDA's winUser wrapper.
# NVDA-only (winUser is imported lazily); a real click cannot be unit-tested, so this is
# verified manually.


def click_at(center, foreground_hwnd, button="left", double=False):
	"""Move the cursor to `center` (screen x, y) and click there.

	Brings `foreground_hwnd` forward first: a synthesized click on an inactive window only
	activates it, so the control is never clicked unless the window is already active. The short
	waits (cursor settle before pressing, a brief hold between press and release, a gap between
	the two presses of a double-click) make apps register a real click rather than a ghost one.
	`button` is "left" or "right"; `double` repeats the press for a double-click.
	"""
	import time

	import winUser

	x, y = center
	if foreground_hwnd and winUser.getForegroundWindow() != foreground_hwnd:
		winUser.setForegroundWindow(foreground_hwnd)
		time.sleep(0.1)
	winUser.setCursorPos(x, y)
	time.sleep(0.05)  # let the cursor arrival register before pressing
	if button == "right":
		down, up = winUser.MOUSEEVENTF_RIGHTDOWN, winUser.MOUSEEVENTF_RIGHTUP
	else:
		down, up = winUser.MOUSEEVENTF_LEFTDOWN, winUser.MOUSEEVENTF_LEFTUP
	for i in range(2 if double else 1):
		if i:
			time.sleep(0.05)  # separate the two presses of a double-click
		winUser.mouse_event(down, 0, 0, 0, 0)
		time.sleep(0.03)  # hold briefly so the control registers a real press
		winUser.mouse_event(up, 0, 0, 0, 0)
