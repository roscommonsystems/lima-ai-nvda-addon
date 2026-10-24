# -*- coding: UTF-8 -*-
# LIMA NVDA add-on: credit usage client. Standard library only; no NVDA imports.
#
# Asks the LIMA backend (lima-addon-auth-server POST /usage) how much of the user's
# included AI credit is spent, and words the answer the way LIMA desktop's Subscription
# dialog does: "Credits used this month: 34% — resets in 4 days".
#
# The server sends a PERCENTAGE and nothing else. It holds the OpenRouter key, the dollar
# cap and the dollar balance and does the division itself, so none of them reach this
# machine. Nothing here should try to reconstruct them.

import datetime
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# Endpoint the request is POSTed to. Unset here for the same reason as vision.ENDPOINT_URL:
# the plugin assigns it at init from firebase_config.LIMA_BACKEND_URL, which binds the
# add-on to the dev or prod backend chosen at build time.
ENDPOINT_URL = None

#: Reset policies this build knows how to word. Anything else is treated as unknown, so a
#: policy added to the server later costs the reset clause and nothing else.
RESETS_MONTHLY = "monthly"
RESETS_NEVER = "never"

#: How near a reset has to be before it is worded as a count rather than a date. Beyond
#: about a week "in 9 days" stops being easier to picture than the date itself.
RESET_SOON_DAYS = 7

# Month names per LIMA response language. Fixed lists rather than strftime("%B"), which
# follows the Windows locale and would mix languages inside one sentence.
_MONTHS = {
	"en": (
		"January", "February", "March", "April", "May", "June",
		"July", "August", "September", "October", "November", "December",
	),
	"tl": (
		"Enero", "Pebrero", "Marso", "Abril", "Mayo", "Hunyo",
		"Hulyo", "Agosto", "Setyembre", "Oktubre", "Nobyembre", "Disyembre",
	),
}


def fetch_credit_usage(id_token, timeout=15, _opener=None):
	"""Ask the backend what percentage of this user's included credit is spent.

	Returns, on success:
		{"valid": True, "usage_percent": int|None, "plan_tier": str,
		 "resets": "monthly"|"never"|None, "resets_at": datetime.date|None}
	and {"valid": False, "error": code} on any failure, where code is "signed_out",
	"network", "rate_limited" (the backend's 429) or "unavailable".

	`usage_percent` is None for an uncapped key. Callers show that the same way as a
	failure: as "Not available", never as 0%.

	One attempt, no retries, like LIMA desktop: the user asked to hear a number, and a
	quick "Not available" is better than a long silence.
	"""
	if not id_token:
		return {"valid": False, "error": "signed_out"}
	if not ENDPOINT_URL:
		log.error("usage.ENDPOINT_URL is unset; the LIMA backend URL was never configured")
		return {"valid": False, "error": "unavailable"}

	request = urllib.request.Request(
		ENDPOINT_URL,
		data=b"{}",
		headers={"Authorization": "Bearer " + id_token, "Content-Type": "application/json"},
		method="POST",
	)
	opener = _opener or urllib.request.urlopen
	try:
		with opener(request, timeout=timeout) as response:
			raw = response.read()
	except urllib.error.HTTPError as e:
		# 404 no_key_provisioned is the ordinary "signed in, nothing used yet" case and 502
		# means OpenRouter could not be read. Neither is worth more than "Not available".
		# The server's own message is logged because the status alone is ambiguous: a bare
		# 404 means the endpoint is missing, which is what a build pointed at a backend
		# without /usage looks like.
		detail = ""
		try:
			detail = e.read().decode("utf-8", "replace")[:300]
		except Exception:
			pass
		log.debug("LIMA credit usage unavailable (HTTP %s): %s", getattr(e, "code", "?"), detail)
		if getattr(e, "code", None) == 429:
			# Still shown as "Not available"; the separate code is for the log and for callers.
			return {"valid": False, "error": "rate_limited"}
		return {"valid": False, "error": "unavailable"}
	except (urllib.error.URLError, TimeoutError, OSError) as e:
		log.debug("LIMA credit usage could not reach the backend: %r", e)
		return {"valid": False, "error": "network"}

	try:
		data = json.loads(raw.decode("utf-8")) if raw else {}
	except ValueError as e:
		log.error("LIMA credit usage received a non-JSON response: %r", e)
		return {"valid": False, "error": "unavailable"}
	if not isinstance(data, dict):
		return {"valid": False, "error": "unavailable"}

	percent = data.get("usage_percent")
	if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float))):
		log.error("LIMA credit usage returned a non-numeric percent: %r", percent)
		return {"valid": False, "error": "unavailable"}

	return {
		"valid": True,
		"usage_percent": int(percent) if percent is not None else None,
		"plan_tier": data.get("plan_tier") or "",
		"resets": reset_policy(data.get("resets")),
		"resets_at": reset_date(data.get("resets_at")),
	}


def reset_policy(value):
	"""The reset policy, or None if missing or not one this build can word."""
	if isinstance(value, str) and value.strip().lower() in (RESETS_MONTHLY, RESETS_NEVER):
		return value.strip().lower()
	return None


def reset_date(value):
	"""The reset date as a date, or None if absent or unparseable.

	The server sends a plain YYYY-MM-DD in UTC: a date and not a timestamp, because the
	day the credit refills is known and the instant within it is not.
	"""
	if not isinstance(value, str) or not value.strip():
		return None
	try:
		return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()
	except ValueError:
		log.debug("LIMA credit usage returned an unparseable reset date: %r", value)
		return None


def today_utc():
	"""Today in UTC, because the server computed the reset date in UTC. The local date
	would let "resets tomorrow" sit next to a date two days away in the user's calendar."""
	return datetime.datetime.now(datetime.timezone.utc).date()


def format_date(value, language):
	"""A reset date as "October 23", "Oktubre 23" or "ngày 23 tháng 10"; "" if unusable.

	No year, because a monthly reset is never more than a month away, and no leading zero.
	"""
	if not isinstance(value, datetime.date):
		return ""
	if language == "vi":
		return "ngày %d tháng %d" % (value.day, value.month)
	months = _MONTHS.get(language, _MONTHS["en"])
	return "%s %d" % (months[value.month - 1], value.day)


def reset_phrase(resets_at, today, text, language):
	""""resets tomorrow", "resets in 4 days", or "resets October 23"; "" if unusable.

	`text` translates a message into the user's LIMA language (announcements.status_text).
	Ported from LIMA desktop's SubscriptionDialog._reset_phrase.
	"""
	if not isinstance(resets_at, datetime.date):
		return ""
	days = (resets_at - today).days
	if days == 1:
		return text("resets tomorrow")
	if 2 <= days <= RESET_SOON_DAYS:
		return text("resets in {n} days").format(n=days)
	# Everything else, including anything at or before today. The server never sends a date
	# in the past - a reset falling today has already happened - but if it did, it reads as
	# a date rather than as "resets in -1 days".
	formatted = format_date(resets_at, language)
	if not formatted:
		return ""
	return text("resets {date}").format(date=formatted)


# The line in two forms. SPOKEN stands alone (NVDA+Alt+U), so it names what it is about.
# FIELD sits after the settings label "Credit usage:", so repeating "Credits used" there
# would read "Credit usage: Credits used this month: ..." - it starts with the figure.
_SPOKEN = {
	"pending": "Credits used: checking…",
	"unavailable": "Credits used: Not available",
	"monthly": "Credits used this month: {percent}%",
	"never": "Credits used: {percent}% (one-time credit — does not reset)",
	"unknown": "Credits used: {percent}%",
}
_FIELD = {
	"pending": "Checking…",
	"unavailable": "Not available",
	"monthly": "{percent}% used this month",
	"never": "{percent}% used (one-time credit — does not reset)",
	"unknown": "{percent}% used",
}


def usage_text(usage, today, text, language, pending=False, field=False):
	"""The line the user hears or reads. A percentage in context, or "Not available".

	`field=True` gives the settings-field form, which follows the "Credit usage:" label;
	otherwise the spoken form, which stands alone.

	There is deliberately no dollar figure to show: nothing on this machine knows it.
	`usage` is a fetch_credit_usage() result (or None).
	"""
	forms = _FIELD if field else _SPOKEN
	if pending:
		return text(forms["pending"])

	usage = usage or {}
	percent = usage.get("usage_percent") if usage.get("valid") else None
	if percent is None:
		return text(forms["unavailable"])

	resets = usage.get("resets")
	if resets == RESETS_MONTHLY:
		line = text(forms["monthly"]).format(percent=percent)
		phrase = reset_phrase(usage.get("resets_at"), today, text, language)
		if phrase:
			line += " — " + phrase
		return line
	if resets == RESETS_NEVER:
		return text(forms["never"]).format(percent=percent)
	# Policy unknown: the percentage is still true, so it is still shown. Inventing a
	# timeframe around it would not be.
	return text(forms["unknown"]).format(percent=percent)


def field_samples(text, language):
	"""The longest lines the settings field can show in this language, for sizing it.

	A wx text field does not grow to fit its value, so the panel measures these and sizes
	the field to the widest. Measured per language because "34% used this month" is
	half the length of its Tagalog form. 100% and the longest month name (September,
	Setyembre; Vietnamese December, "ngày 30 tháng 12") stand in for the widest figures.
	Every reset wording is included, because which is longest differs by language: in
	Tagalog "magre-reset sa loob ng 7 araw" is longer than "magre-reset sa Setyembre 30".
	"""
	widest_date = datetime.date(2026, 12, 30) if language == "vi" else datetime.date(2026, 9, 30)
	samples = []
	# A date a month away (worded as the date), a week away ("in 7 days"), and tomorrow.
	for days_away in (30, RESET_SOON_DAYS, 1):
		today = widest_date - datetime.timedelta(days=days_away)
		samples.append(usage_text(
			{"valid": True, "usage_percent": 100, "resets": RESETS_MONTHLY, "resets_at": widest_date},
			today, text, language, field=True,
		))
	samples.append(usage_text({"valid": True, "usage_percent": 100, "resets": RESETS_NEVER}, widest_date, text, language, field=True))
	samples.append(usage_text(None, widest_date, text, language, field=True))
	return samples


def limit_message(resets, resets_at, text, language):
	"""What the user hears when a request is refused because the credit is spent (402)."""
	message = text("You've used all your LIMA credit for this month.")
	if resets == RESETS_NEVER:
		return message
	formatted = format_date(resets_at, language)
	if formatted:
		return message + " " + text("It resets on {date}.").format(date=formatted)
	# An older server that sends no reset fields, or one that could not work the day out.
	# Both are honest here: the credit does come back monthly.
	return message + " " + text("It resets next month.")
