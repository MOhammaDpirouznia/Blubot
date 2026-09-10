import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from database.connection import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, get_user_wallet_history, modify_wallet_balance
from bot.keyboards import get_wallet_keyboard

TOPUP_AMOUNT = range(1)

async def wallet_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if not user:
            return

    toman_bal = user.wallet_balance // 10
    now = datetime.datetime.utcnow()

    trial_text = ""
    if user.free_until and user.free_until > now:
        days_left = (user.free_until - now).days
        trial_text = f"🎁 <b>طرح رایگان:</b> فعال است ({days_left} روز باقی‌مانده - کارمزد ۰)\n"
    elif user.free_transactions_left > 0:
        trial_text = f"🎁 <b>تراکنش‌های هدیه:</b> {user.free_transactions_left} تراکنش رایگان باقی‌مانده\n"
    else:
        trial_text = "🔒 <b>وضعیت حساب:</b> عادی (محاسبه کارمزد بر روی واریزی‌ها)\n"

    msg = (
        "👛 <b>مدیریت کیف پول و اعتبار پلتفرم</b>\n\n"
        f"💰 <b>موجودی اعتبار شما:</b> {toman_bal:,} تومان\n"
        f"⚙️ <b>نرخ کارمزد:</b> {user.fee_percent}%\n"
        f"🛡 <b>سقف کارمزد هر تراکنش:</b> {user.fee_cap // 10:,} تومان\n"
        f"{trial_text}\n"
        "ℹ️ <i>نکته: از آنجایی که مبالغ مشتریان مستقیماً به کارت بلوبانک خودتان منتقل می‌شود، کارمزد سیستم به ازای هر تراکنش موفق، از اعتبار همین کیف پول کسر می‌گردد.</i>"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=msg,
            parse_mode="HTML",
            reply_markup=get_wallet_keyboard()
        )
    else:
        await update.message.reply_html(
            text=msg,
            reply_markup=get_wallet_keyboard()
        )

async def wallet_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        logs = await get_user_wallet_history(db, user.id, limit=10)

    if not logs:
        await query.message.reply_html("هنوز هیچ تراکنشی در کیف پول شما ثبت نشده است.")
        return

    lines = ["📜 <b>آخرین گردش‌های کیف پول اعتباری:</b>\n"]
    for log in logs:
        toman_amt = abs(log.amount) // 10
        sign = "+" if log.amount > 0 else "-"
        icon = "🟢" if log.amount > 0 else "🔴"
        date_str = log.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"{icon} <code>{sign}{toman_amt:,} تومان</code> | {log.description} ({date_str})")

    lines.append(f"\n👛 <b>مانده فعلی:</b> {user.wallet_balance // 10:,} تومان")
    await query.message.reply_html("\n".join(lines))

# --- TOP UP CONVERSATION ---

async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("۵۰,۰۰۰ تومان", callback_data="topup_50000"), InlineKeyboardButton("۱۰۰,۰۰۰ تومان", callback_data="topup_100000")],
        [InlineKeyboardButton("۲۰۰,۰۰۰ تومان", callback_data="topup_200000"), InlineKeyboardButton("۵۰۰,۰۰۰ تومان", callback_data="topup_500000")],
        [InlineKeyboardButton("مبلغ دلخواه", callback_data="topup_custom")],
        [InlineKeyboardButton("بازگشت", callback_data="wallet_back")]
    ])

    await query.edit_message_text(
        "💳 <b>افزایش اعتبار کیف پول:</b>\n\n"
        "لطفاً مبلغ مورد نظر خود را برای شارژ انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def preset_topup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "wallet_back":
        await wallet_menu_handler(update, context)
        return

    if data == "topup_custom":
        await query.answer()
        await query.edit_message_text("لطفاً مبلغ دلخواه خود را به <b>تومان</b> وارد کنید:\n(مثال: <code>150000</code>)", parse_mode="HTML")
        return TOPUP_AMOUNT

    # Process preset amount
    toman = int(data.replace("topup_", ""))
    rials = toman * 10
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        new_balance = await modify_wallet_balance(
            db=db,
            user_id=user.id,
            amount=rials,
            tx_type="DEPOSIT",
            description=f"شارژ کیف پول ({toman:,} تومان)"
        )

    await query.answer("اعتبار افزایش یافت!")
    await query.edit_message_text(
        f"✅ <b>کیف پول شما با موفقیت شارژ شد!</b>\n\n"
        f"💰 مبلغ افزوده شده: {toman:,} تومان\n"
        f"👛 موجودی جدید: {new_balance // 10:,} تومان",
        parse_mode="HTML"
    )

async def custom_topup_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("،", "")
    if not text.isdigit():
        await update.message.reply_html("❌ لطفاً فقط عدد وارد فرمایید.")
        return TOPUP_AMOUNT

    toman = int(text)
    if toman < 10000:
        await update.message.reply_html("حداقل مبلغ شارژ ۱۰,۰۰۰ تومان می‌باشد.")
        return TOPUP_AMOUNT

    rials = toman * 10
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        new_balance = await modify_wallet_balance(
            db=db,
            user_id=user.id,
            amount=rials,
            tx_type="DEPOSIT",
            description=f"شارژ دستی کیف پول ({toman:,} تومان)"
        )

    await update.message.reply_html(
        f"✅ <b>کیف پول شما با موفقیت شارژ شد!</b>\n\n"
        f"💰 مبلغ افزوده شده: {toman:,} تومان\n"
        f"👛 موجودی جدید: {new_balance // 10:,} تومان"
    )
    return ConversationHandler.END

def get_topup_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(preset_topup_handler, pattern="^topup_custom$")
        ],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_topup_received)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
