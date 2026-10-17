# -*- coding: UTF-8 -*-
# LIMA AI NVDA add-on: dynamic web narration worker.
# Dependency-injected (no NVDA imports) so it is unit-testable standalone.

import threading


class WebNarrator:
	"""Toggle-controlled, browser-gated narrator of on-screen web changes.

	`capture` and `vision` are injected modules/objects; `speak(text)` must be
	safe to call from a background thread (the caller marshals to NVDA's main
	thread). The network describe call runs on the timer thread; overlap is
	avoided because ticks are sequential.

	Failures are reported through `on_error(code, error, stopped)`, also from the timer
	thread. A failure that every later tick would repeat (the month's credit is used up,
	or the user signed out) stops narration and reports `stopped=True`. Anything else
	(network, a service error, a capture failure) is reported once and narration carries
	on; the same failure is not repeated every tick, only after a success or a different
	failure.
	"""

	#: Failures no later tick can recover from, so narration stops instead of failing on
	#: every interval.
	STOPPING_CODES = ("credit_exhausted", "signed_out")

	def __init__(self, capture, vision, get_token, speak, get_language=lambda: "en", interval=6.0, change_threshold=0.03, on_error=lambda code, error, stopped: None):
		self._capture = capture
		self._vision = vision
		self._get_token = get_token
		self._speak = speak
		self._get_language = get_language
		self._on_error = on_error
		self._interval = interval
		self._change_threshold = change_threshold
		self._active = False
		self._timer = None
		self._last_thumb = None
		self._last_full = None
		self._last_description = None
		self._last_error_code = None

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
		self._last_error_code = None
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
		if not self._active:
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
			self._last_thumb = thumb
			self._last_full = after_full
			token = self._get_token()
			if not token:
				self._report("signed_out", None)
				return
			text = self._vision.describe_changes(before_full, after_full, token, previous=self._last_description, language=self._get_language())
			self._last_error_code = None  # a success ends any failure streak
			if text and text != self._vision.NO_CHANGE and text != self._last_description:
				self._last_description = text
				self._speak(text)
		except Exception as e:
			# VisionError carries a speakable code; anything else here came from capturing
			# the screen.
			self._report(getattr(e, "code", None) or "capture", e)

	def _report(self, code, error):
		if code in self.STOPPING_CODES:
			self.stop()
			self._on_error(code, error, True)
			return
		if code == self._last_error_code:
			return  # already told the user; don't repeat it every interval
		self._last_error_code = code
		self._on_error(code, error, False)
