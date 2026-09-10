import datetime
from telegram import Update
from telegram.ext import ContextTypes
from database.connection import AsyncSessionLocal
from database.crud import get_or_create_user
from bot.keyboards import get_main_keyboard
import config

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    if not user_tg:
        return

    is_admin = (user_tg.id == config.ADMIN_TELEGRAM_ID)

    async with AsyncSessionLocal() as db:
        user, is_new = await get_or_create_user(
            db=db,
            telegram_id=user_tg.id,
            username=user_tg.username,
            first_name=user_tg.first_name
        )

    toman_balance = user.wallet_balance // 10
    welcome_msg = (
        f"سلام <b>{user_tg.first_name}</b> عزیز! 👋\n"
        "به ربات درگاه هوشمند کارت‌به‌کارت <b>بلوپال (BluPal)</b> خوش آمدید.\n\n"
        "🚀 <b>مزایای این سیستم:</b>\n"
        "• اتصال مستقیم به بلوبانک از طریق <b>نشست فعال (Active Session)</b>\n"
        "• عدم وابستگی به گوشی موبایل یا فورواردر پیامک (SMS Forwarder)\n"
        "• تشخیص آنی واریزی با تطبیق دقیق مبلغ و ثبت لحظه‌ای\n"
        "• دریافت آنی نام واریزکننده، شماره کارت و کد رهگیری\n"
        "• وب‌سرویس REST و وب‌هوک برای اتصال به سایت و فروشگاه‌ها\n\n"
    )

    if is_new:
        welcome_msg += "🎁 <b>هدیه عضویت:</b> ماه اول استفاده برای شما <b>کاملاً رایگان (کارمزد ۰)</b> فعال گردید!\n\n"

    welcome_msg += (
        f"👛 <b>موجودی کیف پول:</b> {toman_balance:,} تومان\n"
        f"⚙️ <b>تعرفه کارمزد شما:</b> {user.fee_percent}% (تا سقف {user.fee_cap // 10:,} تومان)\n\n"
        "از منوی زیر بخش مورد نظر خود را انتخاب فرمایید:"
    )

    await update.message.reply_html(
        text=welcome_msg,
        reply_markup=get_main_keyboard(is_admin)
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 <b>راهنمای کار با سیستم بلوپال:</b>\n\n"
        "۱. <b>اتصال حساب:</b> از دکمه <i>حساب‌ها و نشست‌ها</i> شماره متصل به بلوبانک خود را وارد کنید تا نشست فعال ثبت شود.\n\n"
        "۲. <b>صدور فاکتور:</b> می‌توانید از دکمه <i>صدور فاکتور سریع</i> در ربات یا از طریق <i>API</i> برای فروشگاه خود فاکتور بسازید.\n\n"
        "۳. <b>تطبیق خودکار:</b> سیستم برای هر فاکتور چند تومان آفست تصادفی اضافه می‌کند. به محض واریز دقیق مبلغ توسط مشتری، فاکتور تأیید و وب‌هوک ارسال می‌شود.\n\n"
        "۴. <b>کیف پول و کارمزد:</b> چون پول مستقیماً به حساب شما می‌آید، کارمزد تراکنش‌ها به صورت خودکار از موجودی کیف پول اعتباری شما در ربات کسر می‌گردد."
    )
    await update.message.reply_html(msg)
