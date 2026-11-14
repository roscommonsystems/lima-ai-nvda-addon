# -*- coding: UTF-8 -*-
"""Command announcements in the selected LIMA response language."""

VIETNAMESE = {
	"LIMA AI add-on is running": "Tiện ích LIMA AI đang hoạt động.",
	"Describing screen.": "Đang mô tả màn hình.",
	"Describing element.": "Đang mô tả đối tượng đang được chọn.",
	"Asking LIMA.": "Đang hỏi LIMA.",
	"The element description is already open.": "Cửa sổ mô tả đối tượng đang mở.",
	"You are not signed in to LIMA AI. Press NVDA+Alt+A to sign in with Google.": "Bạn chưa đăng nhập LIMA AI. Nhấn NVDA+Alt+A để đăng nhập bằng Google.",
	"Your LIMA AI sign-in is no longer valid, so you have been signed out. Press NVDA+Alt+A to sign in again.": "Phiên đăng nhập LIMA AI của bạn không còn hiệu lực, nên bạn đã được đăng xuất. Nhấn NVDA+Alt+A để đăng nhập lại.",
	"Still describing, please wait.": "Đang mô tả, vui lòng chờ.",
	"Still describing the previous screen, please wait.": "Đang mô tả màn hình trước đó, vui lòng chờ.",
	"Could not capture the screen or element.": "Không thể chụp màn hình hoặc đối tượng.",
	"Could not capture the screen.": "Không thể chụp màn hình.",
	"Could not reach the AI service. Check your connection and try again.": "Không thể kết nối với dịch vụ AI. Hãy kiểm tra kết nối và thử lại.",
	"The AI service returned an error. Please try again.": "Dịch vụ AI báo lỗi. Vui lòng thử lại.",
	"No description was returned. Try again.": "Không nhận được mô tả. Vui lòng thử lại.",
	"The focused element has no visible location to capture. Move to a control and try again.": "Đối tượng đang được chọn không có vị trí hiển thị để chụp. Hãy chuyển đến một điều khiển và thử lại.",
	"Web narration on": "Đã bật mô tả trang web.",
	"Web narration off": "Đã tắt mô tả trang web.",
	"Web page update:": "Cập nhật trang web:",
	"Search cancelled.": "Đã hủy tìm kiếm.",
	"Finding {desc}.": "Đang tìm {desc}.",
	"I could not find anything to click here.": "Không tìm thấy đối tượng nào để nhấp tại đây.",
	"I could not find {desc}.": "Không tìm thấy {desc}.",
	"Clicked {name}.": "Đã nhấp vào {name}.",
	"Double-clicked {name}.": "Đã nhấp hai lần vào {name}.",
	"Right-clicked {name}.": "Đã nhấp chuột phải vào {name}.",
	"The click could not be performed. Please try again.": "Không thể thực hiện thao tác nhấp. Vui lòng thử lại.",
	"Too many requests. Please wait a moment and try again.": "Quá nhiều yêu cầu. Vui lòng chờ một lát rồi thử lại.",
	"The AI service is slow right now. Please try again.": "Dịch vụ AI hiện đang phản hồi chậm. Vui lòng thử lại.",
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
	# Sign-up refusals from the backend's signup guard (signup.py), and their wait phrases.
	"LIMA AI cannot create a free account with this email address, so you have been signed out. Press NVDA+Alt+A to sign in with a different Google account, or contact Roscommon Systems at hello@roscommonsystems.com.": "LIMA AI không thể tạo tài khoản miễn phí với địa chỉ email này, nên bạn đã được đăng xuất. Nhấn NVDA+Alt+A để đăng nhập bằng một tài khoản Google khác, hoặc liên hệ Roscommon Systems qua email hello@roscommonsystems.com.",
	"LIMA AI can't create new free accounts right now. Please try again later.": "LIMA AI hiện không thể tạo tài khoản miễn phí mới. Vui lòng thử lại sau.",
	"Too many new LIMA AI accounts have been created on this computer recently. Please try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com.": "Gần đây có quá nhiều tài khoản LIMA AI mới được tạo trên máy tính này. Vui lòng thử lại sau {wait}, hoặc liên hệ Roscommon Systems qua email hello@roscommonsystems.com.",
	"Too many new LIMA AI accounts have been created from this internet connection recently. Please try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com.": "Gần đây có quá nhiều tài khoản LIMA AI mới được tạo từ kết nối internet này. Vui lòng thử lại sau {wait}, hoặc liên hệ Roscommon Systems qua email hello@roscommonsystems.com.",
	"a little while": "một lúc",
	"about a minute": "khoảng một phút",
	"about {n} minutes": "khoảng {n} phút",
	"about an hour": "khoảng một giờ",
	"about {n} hours": "khoảng {n} giờ",
	"about {n} days": "khoảng {n} ngày",
}

# Tagalog command text. Only the credit-usage, sign-in and sign-up lines so far: the add-on's other command
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
	# Sign-up refusals from the backend's signup guard (signup.py), and their wait phrases.
	"LIMA AI cannot create a free account with this email address, so you have been signed out. Press NVDA+Alt+A to sign in with a different Google account, or contact Roscommon Systems at hello@roscommonsystems.com.": "Hindi makagawa ang LIMA AI ng libreng account gamit ang email address na ito, kaya na-sign out ka na. Pindutin ang NVDA+Alt+A para mag-sign in gamit ang ibang Google account, o makipag-ugnayan sa Roscommon Systems sa hello@roscommonsystems.com.",
	"You are not signed in to LIMA AI. Press NVDA+Alt+A to sign in with Google.": "Hindi ka pa naka-sign in sa LIMA AI. Pindutin ang NVDA+Alt+A para mag-sign in gamit ang Google.",
	"Your LIMA AI sign-in is no longer valid, so you have been signed out. Press NVDA+Alt+A to sign in again.": "Hindi na valid ang iyong pag-sign in sa LIMA AI, kaya na-sign out ka na. Pindutin ang NVDA+Alt+A para mag-sign in muli.",
	"LIMA AI can't create new free accounts right now. Please try again later.": "Hindi makagawa ang LIMA AI ng mga bagong libreng account sa ngayon. Pakisubukang muli mamaya.",
	"Too many new LIMA AI accounts have been created on this computer recently. Please try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com.": "Masyadong maraming bagong LIMA AI account ang ginawa sa computer na ito kamakailan. Pakisubukang muli pagkalipas ng {wait}, o makipag-ugnayan sa Roscommon Systems sa hello@roscommonsystems.com.",
	"Too many new LIMA AI accounts have been created from this internet connection recently. Please try again in {wait}, or contact Roscommon Systems at hello@roscommonsystems.com.": "Masyadong maraming bagong LIMA AI account ang ginawa mula sa koneksyon sa internet na ito kamakailan. Pakisubukang muli pagkalipas ng {wait}, o makipag-ugnayan sa Roscommon Systems sa hello@roscommonsystems.com.",
	"a little while": "kaunting sandali",
	"about a minute": "mga isang minuto",
	"about {n} minutes": "mga {n} minuto",
	"about an hour": "mga isang oras",
	"about {n} hours": "mga {n} oras",
	"about {n} days": "mga {n} araw",
}

_BY_LANGUAGE = {"vi": VIETNAMESE, "tl": TAGALOG}


def status_text(message, language, translate):
	"""Use the selected LIMA language's command text when it has one; otherwise NVDA's
	translation."""
	table = _BY_LANGUAGE.get(language, {})
	if message in table:
		return table[message]
	return translate(message)
