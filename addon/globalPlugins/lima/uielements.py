# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: find on-screen clickable elements for click-by-description.
#
# "Clickable" matches the flagship's mouse-click enumeration (lima tools_ui_tree:
# filter_out_elements defaults, used by return_clickable_elements_list_root_tree): any named,
# on-screen control the keyboard can focus. This deliberately does NOT require an Invoke/Toggle/
# SelectionItem pattern, so edit fields such as search and address bars count as click targets,
# the same as in the flagship. `accepts` drops the unnamed and zero-size nodes afterwards.
#
# Enumeration uses a UI Automation cached query (the same UIA mechanism the flagship uses).
# It MUST be called from a worker thread, not NVDA's GUI thread: it enters the multithreaded
# COM apartment, which is where a UIA tree walk returns the full window, not just the chrome.
# The UIA imports are lazy so the pure helpers stay unit-testable without NVDA.

import collections

#: One clickable element. `center`/`rect` are in screen pixels; `role_text` is the readable
#: role shown to the model; elements are numbered from 1 in query order.
Element = collections.namedtuple("Element", ["number", "name", "role_text", "center", "rect"])

_CUIAUTOMATION_CLSID = "{ff48dba4-60ef-4201-aa87-54103eef594e}"


def accepts(name, width, height):
	"""Pure filter for the two checks the UIA condition cannot express: a non-empty name and a
	positive on-screen size. Enabled, on-screen, focusable, and clickable-pattern are already
	enforced by the query itself."""
	return bool(name and name.strip()) and width > 0 and height > 0


def format_elements_for_prompt(elements):
	"""Render the numbered list the model chooses from, one per line:
	"N. Name | Role | center X,Y". Returns "" for an empty list."""
	lines = []
	for e in elements:
		x, y = e.center
		lines.append(f"{e.number}. {e.name} | {e.role_text} | center {x},{y}")
	return "\n".join(lines)


def enumerate_clickable(foreground_hwnd, max_elements=200):
	"""Return (elements, debug): up to `max_elements` click-target Element records for the
	window `foreground_hwnd`, plus a short diagnostic string.

	A click target is any on-screen control the keyboard can focus, matching the flagship's
	mouse-click enumeration (tools_ui_tree.filter_out_elements defaults: focusable + on-screen).
	That keeps edit fields such as search and address bars, which support no Invoke/Toggle/
	Selection pattern. `accepts` then drops the unnamed or zero-size results.

	Call from a WORKER thread. Entering the multithreaded apartment here is what makes the UIA
	query return the whole window instead of only its title-bar chrome. NVDA-only; verified
	manually and with scratchpad/uia_probe_patterns.py.
	"""
	if not foreground_hwnd:
		return [], "no window handle"
	try:
		import comtypes
		import comtypes.client
		try:
			from comInterfaces import UIAutomationClient as UIA
		except ImportError:
			from comtypes.gen import UIAutomationClient as UIA
	except ImportError:
		return [], "UIA modules unavailable"
	try:
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
	except OSError:
		pass  # this thread already has an apartment; use it rather than failing
	try:
		try:
			client = comtypes.client.CreateObject(_CUIAUTOMATION_CLSID, interface=UIA.IUIAutomation)
			root = client.ElementFromHandle(foreground_hwnd)
		except Exception as e:
			return [], f"client error {e!r}"
		if not root:
			return [], "no root element"
		try:
			cache = client.CreateCacheRequest()
			for prop in (
				UIA.UIA_NamePropertyId, UIA.UIA_LocalizedControlTypePropertyId,
				UIA.UIA_BoundingRectanglePropertyId,
			):
				cache.AddProperty(prop)
			# A click target is any on-screen control the keyboard can focus. This matches the
			# flagship's mouse-click enumeration (filter_out_elements defaults: focusable +
			# on-screen) and, unlike a pattern filter, keeps edit fields such as search and
			# address bars, which expose no Invoke/Toggle/SelectionItem pattern.
			condition = client.CreateAndCondition(
				client.CreatePropertyCondition(UIA.UIA_IsKeyboardFocusablePropertyId, True),
				client.CreatePropertyCondition(UIA.UIA_IsOffscreenPropertyId, False),
			)
			found = root.FindAllBuildCache(UIA.TreeScope_Subtree, condition, cache)
		except Exception as e:
			return [], f"query error {e!r}"
		elements = []
		total = found.Length if found else 0
		for i in range(total):
			if len(elements) >= max_elements:
				break
			try:
				el = found.GetElement(i)
				name = (el.CachedName or "").strip()
				rect = el.CachedBoundingRectangle
				width = rect.right - rect.left
				height = rect.bottom - rect.top
				if not accepts(name, width, height):
					continue
				role_text = (el.CachedLocalizedControlType or "").strip() or "control"
				center = (rect.left + width // 2, rect.top + height // 2)
				elements.append(Element(len(elements) + 1, name, role_text, center, (rect.left, rect.top, width, height)))
			except Exception:
				pass
		return elements, f"found {total} kept {len(elements)}"
	finally:
		comtypes.CoUninitialize()
