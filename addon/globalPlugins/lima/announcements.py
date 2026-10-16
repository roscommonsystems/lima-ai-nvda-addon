# -*- coding: UTF-8 -*-
"""Command announcements in the selected LIMA response language."""

VIETNAMESE = {
	"LIMA AI add-on is running": "Tiện ích LIMA AI đang hoạt động.",
	"Describing screen.": "Đang mô tả màn hình.",
	"Describing element.": "Đang mô tả phần tử đang được chọn.",
	"Sign in with Google in LIMA AI settings to use this feature.": "Hãy đăng nhập bằng Google trong phần cài đặt LIMA AI để sử dụng tính năng này.",
	"Still describing, please wait.": "Đang mô tả, vui lòng chờ.",
	"Still describing the previous screen, please wait.": "Đang mô tả màn hình trước đó, vui lòng chờ.",
	"Could not capture the screen or element.": "Không thể chụp màn hình hoặc phần tử.",
	"Could not capture the screen.": "Không thể chụp màn hình.",
	"Could not reach the AI service. Check your connection and try again.": "Không thể kết nối với dịch vụ AI. Hãy kiểm tra kết nối và thử lại.",
	"The AI service returned an error. Please try again.": "Dịch vụ AI báo lỗi. Vui lòng thử lại.",
	"No description was returned. Try again.": "Không nhận được mô tả. Vui lòng thử lại.",
	"The focused element has no visible location to capture. Move to a control and try again.": "Phần tử đang được chọn không có vị trí hiển thị để chụp. Hãy chuyển đến một điều khiển và thử lại.",
	"Web narration on": "Đã bật mô tả trang web.",
	"Web narration off": "Đã tắt mô tả trang web.",
	"Web page update:": "Cập nhật trang web:",
	# Credit usage (NVDA+Alt+U, the settings line, and the out-of-credit message).
	"Credit usage:": "Mức dùng tín dụng:",
	"Credits used this month: {percent}%": "Tín dụng đã dùng trong tháng này: {percent}%",
	"Credits used: {percent}%": "Tín dụng đã dùng: {percent}%",
	"Credits used: {percent}% (one-time credit — does not reset)": "Tín dụng đã dùng: {percent}% (tín dụng một lần — không đặt lại)",
	"Credits used: Not available": "Tín dụng đã dùng: Không có thông tin",
	"Credits used: checking…": "Tín dụng đã dùng: đang kiểm tra…",
	"resets tomorrow": "đặt lại vào ngày mai",
	"resets in {n} days": "đặt lại sau {n} ngày",
	"resets {date}": "đặt lại vào {date}",
	"Checking credit usage.": "Đang kiểm tra mức dùng tín dụng.",
	"You've used all your LIMA credit for this month.": "Bạn đã dùng hết tín dụng LIMA của tháng này.",
	"It resets on {date}.": "Tín dụng sẽ được đặt lại vào {date}.",
	"It resets next month.": "Tín dụng sẽ được đặt lại vào tháng sau.",
	# The settings field, which follows the "Credit usage:" label.
	"Checking…": "Đang kiểm tra…",
	"Not available": "Không có thông tin",
	"{percent}% used this month": "Đã dùng {percent}% trong tháng này",
	"{percent}% used (one-time credit — does not reset)": "Đã dùng {percent}% (tín dụng một lần — không đặt lại)",
	"{percent}% used": "Đã dùng {percent}%",
}

# Tagalog command text. Only the credit-usage lines so far: the add-on's other command
# messages are still spoken in English for Tagalog users (only AI replies are in Tagalog).
TAGALOG = {
	"Credit usage:": "Paggamit ng credits:",
	"Credits used this month: {percent}%": "Nagamit na credits ngayong buwan: {percent}%",
	"Credits used: {percent}%": "Nagamit na credits: {percent}%",
	"Credits used: {percent}% (one-time credit — does not reset)": "Nagamit na credits: {percent}% (isang beses na credit — hindi nagre-reset)",
	"Credits used: Not available": "Nagamit na credits: Hindi available",
	"Credits used: checking…": "Nagamit na credits: sinusuri…",
	"resets tomorrow": "magre-reset bukas",
	"resets in {n} days": "magre-reset sa loob ng {n} araw",
	"resets {date}": "magre-reset sa {date}",
	"Checking credit usage.": "Sinusuri ang paggamit ng credits.",
	"You've used all your LIMA credit for this month.": "Naubos mo na ang iyong LIMA credits para sa buwang ito.",
	"It resets on {date}.": "Magre-reset ito sa {date}.",
	"It resets next month.": "Magre-reset ito sa susunod na buwan.",
	# The settings field, which follows the "Credit usage:" label.
	"Checking…": "Sinusuri…",
	"Not available": "Hindi available",
	"{percent}% used this month": "{percent}% ang nagamit ngayong buwan",
	"{percent}% used (one-time credit — does not reset)": "{percent}% ang nagamit (isang beses na credit — hindi nagre-reset)",
	"{percent}% used": "{percent}% ang nagamit",
}

_BY_LANGUAGE = {"vi": VIETNAMESE, "tl": TAGALOG}


def status_text(message, language, translate):
	"""Use the selected LIMA language's command text when it has one; otherwise NVDA's
	translation."""
	table = _BY_LANGUAGE.get(language, {})
	if message in table:
		return table[message]
	return translate(message)
