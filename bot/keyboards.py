from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import config

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("💳 حساب‌ها و نشست‌ها"), KeyboardButton("👛 کیف پول و اعتبار")],
        [KeyboardButton("🧾 صدور فاکتور سریع"), KeyboardButton("📊 گزارش تراکنش‌ها")],
        [KeyboardButton("🔑 تنظیمات API و وب‌هوک"), KeyboardButton("🛠 راهنما و مستندات")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("👑 پنل مدیریت پلتفرم")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_bank_menu_keyboard(has_active_session: bool) -> InlineKeyboardMarkup:
    buttons = []
    if has_active_session:
        buttons.append([InlineKeyboardButton("🔄 بروزرسانی و تست نشست", callback_data="bank_refresh")])
        buttons.append([InlineKeyboardButton("🗑 قطع اتصال نشست", callback_data="bank_disconnect")])
    else:
        buttons.append([InlineKeyboardButton("📲 ورود و ثبت نشست جدید بلوبانک", callback_data="bank_connect")])
    return InlineKeyboardMarkup(buttons)

def get_wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 افزایش موجودی (شارژ کیف پول)", callback_data="wallet_topup")],
        [InlineKeyboardButton("📜 گردش حساب کیف پول", callback_data="wallet_history")]
    ])

def get_api_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 تنظیم آدرس Webhook", callback_data="set_webhook")],
        [InlineKeyboardButton("🔄 صدور مجدد کلیدهای API", callback_data="regen_api_keys")],
        [InlineKeyboardButton("🧪 ارسال وب‌هوک تستی", callback_data="test_webhook")]
    ])

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار مالی و سود پلتفرم", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ تنظیم نرخ و سقف کارمزد", callback_data="admin_fee_settings")],
        [InlineKeyboardButton("👥 آمار کاربران و نشست‌ها", callback_data="admin_users")]
    ])
