# -*- coding: UTF-8 -*-
"""Command announcements in the selected LIMA response language."""

VIETNAMESE = {
	"The AI service is temporarily busy. Please try again later.": "Dịch vụ AI hiện đang quá tải. Vui lòng thử lại sau.",
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
}


def status_text(message, language, translate):
	"""Use Vietnamese command text when selected; otherwise use NVDA translations."""
	if language == "vi" and message in VIETNAMESE:
		return VIETNAMESE[message]
	return translate(message)
