import uielements
from uielements import Element


def test_accepts_keeps_named_sized():
	assert uielements.accepts("Send", 20, 10)


def test_accepts_rejects_unnamed():
	assert not uielements.accepts("", 20, 10)
	assert not uielements.accepts("   ", 20, 10)


def test_accepts_rejects_zero_or_negative_size():
	assert not uielements.accepts("Send", 0, 10)
	assert not uielements.accepts("Send", 20, 0)


def test_format_elements_numbered_with_name_role_center():
	elements = [
		Element(1, "Send", "button", (10, 20), (0, 0, 20, 40)),
		Element(2, "Home", "link", (30, 40), (0, 0, 10, 10)),
	]
	text = uielements.format_elements_for_prompt(elements)
	assert "1. Send | button | center 10,20" in text
	assert "2. Home | link | center 30,40" in text


def test_format_elements_empty_is_empty_string():
	assert uielements.format_elements_for_prompt([]) == ""
