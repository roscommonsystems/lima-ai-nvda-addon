# -*- coding: UTF-8 -*-
# LIMA AI NVDA add-on: dynamic web narration worker.
# Dependency-injected (no NVDA imports) so it is unit-testable standalone.

import threading
import logging
import time

log = logging.getLogger(__name__)


class WebNarrator:
	"""Toggle-controlled, browser-gated narrator of on-screen web changes.

	`capture` and `vision` are injected modules/objects; `speak(text)` must be
	safe to call from a background thread (the caller marshals to NVDA's main
	thread). The network describe call runs on the timer thread; overlap is
	avoided because ticks are sequential.
	"""

	def __init__(self, capture, vision, get_token, speak, get_language=lambda: "en", interval=6.0, change_threshold=0.03, on_error=None):
		self._capture = capture
		self._vision = vision
		self._get_token = get_token
		self._speak = speak
		self._get_language = get_language
		self._interval = interval
		self._change_threshold = change_threshold
		self._active = False
		self._timer = None
		self._last_thumb = None
		self._last_full = None
		self._last_description = None
		self._on_error = on_error
		self._last_error = None
		self._retry_at = 0.0
		self._retry_delay = 0.0

	@property
	def is_active(self):
		return self._active

	def toggle(self):
		if self._active:
			self.stop()
		else:
			self.start()
		return self._active

	def start(self):
		self._active = True
		self._last_thumb = None
		self._last_full = None
		self._last_description = None
		self._last_error = None
		self._retry_at = 0.0
		self._retry_delay = 0.0
		self._schedule()

	def stop(self):
		self._active = False
		if self._timer is not None:
			self._timer.cancel()
			self._timer = None

	def _schedule(self):
		if not self._active:
			return
		self._timer = threading.Timer(self._interval, self._tick)
		self._timer.daemon = True
		self._timer.start()

	def _tick(self):
		try:
			self._check_once()
		finally:
			self._schedule()

	def _check_once(self):
		if not self._active or time.monotonic() < self._retry_at:
			return
		try:
			if not self._capture.is_browser_title(self._capture.foreground_window_title()):
				self._last_thumb = None
				self._last_full = None
				self._last_description = None
				return
			thumb = self._capture.capture_thumbnail_rgb()
			if self._last_thumb is None:
				self._last_thumb = thumb
				self._last_full = self._capture.capture_screen_png()
				return
			if not self._capture.frames_differ(self._last_thumb, thumb, self._change_threshold):
				return
			after_full = self._capture.capture_screen_png()
			before_full = self._last_full
			text = self._vision.describe_changes(before_full, after_full, self._get_token(), previous=self._last_description, language=self._get_language())
			self._last_thumb = thumb
			self._last_full = after_full
			self._last_error = None
			self._retry_at = 0.0
			self._retry_delay = 0.0
			if text and text != self._vision.NO_CHANGE and text != self._last_description:
				self._last_description = text
				self._speak(text)
		except Exception as error:
			code = getattr(error, "code", "api_error")
			log.exception("LIMA web narration failed (%s)", code)
			# Keep the last successful frame so a failed change can be retried.
			if code == "rate_limited":
				self._retry_delay = min(300.0, max(60.0, self._retry_delay * 2))
			else:
				self._retry_delay = 30.0
			self._retry_at = time.monotonic() + self._retry_delay
			if self._active and code != self._last_error:
				self._last_error = code
				if self._on_error is not None:
					self._on_error(code)
