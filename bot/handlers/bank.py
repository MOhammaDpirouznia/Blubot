import re
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)
from database.connection import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_user_sessions,
    save_bank_session,
    delete_session
)
from blubank.client import BluBankClient
from blubank.crypto import encrypt_session_data
from blubank.session_manager import SessionManager
from bot.keyboards import get_bank_menu_keyboard

# Conversation States
PHONE_INPUT, OTP_INPUT = range(2)

async def bank_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if not user:
            return
        sessions = await get_user_sessions(db, user.id)

    if not sessions:
        msg = (
            "💳 <b>مدیریت حساب‌ها و نشست‌های بلوبانک</b>\n\n"
            "هنوز هیچ حساب بلوبانکی به ربات متصل نشده است.\n"
            "با فشردن دکمه زیر، نشست فعال بلوبانک خود را در کمتر از ۱ دقیقه ثبت کنید:"
        )
        has_active = False
    else:
        active_sess = sessions[0]
        toman_bal = active_sess.last_balance // 10
        card_fmt = " ".join([active_sess.card_number[i:i+4] for i in range(0, len(active_sess.card_number), 4)])
        status_icon = "🟢 فعال" if active_sess.status == "ACTIVE" else "🔴 غیرفعال"

        msg = (
            "💳 <b>اطلاعات نشست بلوبانک متصل:</b>\n\n"
            f"👤 <b>نام صاحب حساب:</b> {active_sess.account_name or 'کاربر بلوبانک'}\n"
            f"💳 <b>شماره کارت:</b> <code>{card_fmt}</code>\n"
            f"🏦 <b>شماره شبا:</b> <code>{active_sess.sheba_number or '---'}</code>\n"
            f"📱 <b>شماره تلفن:</b> <code>{active_sess.phone_number}</code>\n"
            f"📶 <b>وضعیت نشست:</b> {status_icon}\n"
            f"💰 <b>آخرین موجودی استعلام شده:</b> {toman_bal:,} تومان\n\n"
            "این نشست به صورت خودکار واریزی‌های جدید به این کارت را پایش می‌کند."
        )
        has_active = (active_sess.status == "ACTIVE")

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            parse_mode="HTML",
            reply_markup=get_bank_menu_keyboard(has_active)
        )
    else:
        await update.message.reply_html(
            text=msg,
            reply_markup=get_bank_menu_keyboard(has_active)
        )

# --- CONNECT CONVERSATION ---

async def start_connect_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📲 <b>مرحله ۱ از ۲:</b> لطفاً <b>شماره موبایل متصل به بلوبانک</b> خود را ارسال فرمایید:\n"
        "(مثال: <code>09123456789</code>)\n\n"
        "برای لغو فرآیند /cancel را ارسال کنید.",
        parse_mode="HTML"
    )
    return PHONE_INPUT

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    clean_phone = re.sub(r"[^\d]", "", phone)

    if len(clean_phone) < 10 or not clean_phone.startswith("09"):
        await update.message.reply_html("❌ شماره وارد شده معتبر نیست. لطفاً شماره صحیح مانند <code>09121234567</code> ارسال کنید:")
        return PHONE_INPUT

    context.user_data["blu_phone"] = clean_phone
    await update.message.reply_html("⏳ در حال ارتباط با سرور بلوبانک و ارسال کد تأیید...")

    # Request OTP from BluBank client
    client = BluBankClient()
    res = await client.request_otp(clean_phone)

    if not res.get("success"):
        await update.message.reply_html("❌ ارسال کد با خطا مواجه شد. لطفاً کمی بعد مجدداً تلاش کنید.")
        return ConversationHandler.END

    context.user_data["temp_token"] = res.get("temp_token")

    await update.message.reply_html(
        "📩 <b>مرحله ۲ از ۲:</b> کد تأیید پیامک شده از سوی بلوبانک را وارد کنید:\n"
        "<i>(کد ۵ یا ۶ رقمی پیامک شده به گوشی شما)</i>"
    )
    return OTP_INPUT

async def otp_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    phone = context.user_data.get("blu_phone")
    temp_token = context.user_data.get("temp_token")

    await update.message.reply_html("⏳ در حال تأیید کد و ثبت نشست فعال...")

    client = BluBankClient()
    verify_res = await client.verify_otp(phone, otp, temp_token)

    if not verify_res.get("success"):
        await update.message.reply_html("❌ کد وارد شده نادرست یا منقضی شده است. فرآیند لغو شد.")
        return ConversationHandler.END

    # Fetch user's card info
    cards_info = await client.get_cards_and_accounts()
    card_data = cards_info.get("cards", [{}])[0]

    card_num = card_data.get("cardNumber", "6219861000000000")
    sheba = card_data.get("sheba", "")
    holder_name = card_data.get("holderName", "کاربر بلوبانک")

    # Encrypt session tokens
    token_dict = {
        "access_token": client.access_token,
        "refresh_token": client.refresh_token,
        "device_id": client.device_id,
        "cookies": client.cookies
    }
    encrypted_tokens = encrypt_session_data(token_dict)

    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if user:
            await save_bank_session(
                db=db,
                user_id=user.id,
                phone_number=phone,
                card_number=card_num,
                sheba_number=sheba,
                account_name=holder_name,
                encrypted_tokens=encrypted_tokens
            )

    card_fmt = " ".join([card_num[i:i+4] for i in range(0, len(card_num), 4)])
    await update.message.reply_html(
        "🎉 <b>نشست فعال بلوبانک با موفقیت ثبت شد!</b>\n\n"
        f"💳 <b>کارت متصل:</b> <code>{card_fmt}</code>\n"
        f"👤 <b>صاحب حساب:</b> {holder_name}\n"
        "🟢 وضعیت نشست: <b>فعال و در حال پایش تراکنش‌ها</b>\n\n"
        "از این پس کلیه واریزی‌ها به این کارت توسط سیستم شناسایی و اطلاع‌رسانی خواهند شد."
    )
    return ConversationHandler.END

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html("عملیات لغو شد.")
    return ConversationHandler.END

async def refresh_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال استعلام...")
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        sessions = await get_user_sessions(db, user.id)
        if sessions:
            is_valid = await SessionManager.refresh_and_validate(db, sessions[0])
            status_text = "🟢 نشست معتبر و فعال است." if is_valid else "🔴 نشست منقضی شده، لطفاً دوباره وارد شوید."
            await query.message.reply_html(f"نتیجه بررسی: {status_text}")
        else:
            await query.message.reply_html("هیچ نشستی برای بررسی یافت نشد.")

async def disconnect_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        sessions = await get_user_sessions(db, user.id)
        if sessions:
            await delete_session(db, sessions[0].id)
            await query.message.reply_html("🗑 نشست با موفقیت حذف و ارتباط با بلوبانک قطع شد.")
        else:
            await query.message.reply_html("نشستی برای حذف وجود ندارد.")

def get_connect_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_connect_flow, pattern="^bank_connect$")],
        states={
            PHONE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_received)],
            OTP_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, otp_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel_flow)],
        per_message=False
    )
