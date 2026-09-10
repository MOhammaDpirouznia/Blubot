import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, filters
)
from database.connection import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_user_sessions,
    create_invoice,
    get_user_invoices
)
from core.matching_engine import MatchingEngine
import config

INVOICE_AMOUNT = range(1)

async def start_create_invoice_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if not user:
            return
        sessions = await get_user_sessions(db, user.id)

    active_sessions = [s for s in sessions if s.status == "ACTIVE"]
    if not active_sessions:
        await update.message.reply_html(
            "⚠️ <b>هیچ نشست یا کارت فعالی ثبت نشده است!</b>\n\n"
            "برای صدور فاکتور، ابتدا باید از بخش <i>حساب‌ها و نشست‌ها</i>، بلوبانک خود را متصل کنید."
        )
        return ConversationHandler.END

    context.user_data["target_card"] = active_sessions[0].card_number
    context.user_data["target_session_id"] = active_sessions[0].id

    await update.message.reply_html(
        "🧾 <b>صدور فاکتور پرداخت سریع</b>\n\n"
        "لطفاً <b>مبلغ فاکتور را به تومان</b> وارد نمایید:\n"
        "(مثال: <code>50000</code> یا <code>250000</code>)\n\n"
        "جهت انصراف /cancel را بفرستید."
    )
    return INVOICE_AMOUNT

async def invoice_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("،", "")
    if not text.isdigit():
        await update.message.reply_html("❌ لطفاً مبلغ را فقط به صورت عدد (تومان) وارد فرمایید:")
        return INVOICE_AMOUNT

    toman = int(text)
    if toman < 10000:
        await update.message.reply_html("حداقل مبلغ فاکتور ۱۰,۰۰۰ تومان (۱۰۰,۰۰۰ ریال) است:")
        return INVOICE_AMOUNT

    rials = toman * 10
    card_number = context.user_data.get("target_card")
    session_id = context.user_data.get("target_session_id")
    user_tg = update.effective_user

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)

        # Allocate unique offset
        offset, final_amount = await MatchingEngine.allocate_unique_offset(db, card_number, rials)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=config.INVOICE_TTL_MINUTES)

        invoice = await create_invoice(
            db=db,
            user_id=user.id,
            card_number=card_number,
            base_amount=rials,
            random_offset=offset,
            final_amount=final_amount,
            expires_at=expires_at,
            mode="live",
            session_id=session_id
        )

    toman_final = final_amount // 10
    card_clean = card_number.replace("-", "").replace(" ", "")
    card_fmt = " ".join([card_clean[i:i+4] for i in range(0, len(card_clean), 4)])
    payment_link = f"{config.BASE_URL}/payment/{invoice.public_token}"

    customer_text = (
        "💳 <b>اطلاعات پرداخت فاکتور</b>\n\n"
        f"🔢 <b>شماره کارت مقصد:</b>\n<code>{card_fmt}</code>\n"
        f"🏦 <b>بانک:</b> سامان (بلوبانک)\n\n"
        f"💰 <b>مبلغ دقیق واریز:</b> <code>{toman_final:,}</code> تومان\n\n"
        "🔗 <b>لینک صفحه پرداخت:</b>\n"
        f"{payment_link}\n\n"
        "⚠️ <i>توجه: لطفاً دقیقاً مبلغ فوق را واریز نمایید تا تراکنش شما به صورت لحظه‌ای تأیید شود.</i>"
    )

    msg = (
        f"✅ <b>فاکتور شماره #{invoice.id} با موفقیت صادر شد!</b>\n\n"
        f"💰 مبلغ درخواستی: {toman:,} تومان\n"
        f"🔢 مبلغ نهایی با آفست: <b>{toman_final:,} تومان</b>\n"
        f"⏱ مهلت پرداخت: {config.INVOICE_TTL_MINUTES} دقیقه\n\n"
        "👇 <b>متن آماده ارسال برای مشتری:</b>\n"
        "─────────────────\n"
        f"{customer_text}\n"
        "─────────────────\n"
        "<i>به محض واریز توسط مشتری، پیام تأیید دریافت خواهید کرد.</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 باز کردن صفحه پرداخت", url=payment_link)]
    ])

    await update.message.reply_html(text=msg, reply_markup=keyboard)
    return ConversationHandler.END

async def list_transactions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tg = update.effective_user
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, user_tg.id)
        if not user:
            return
        invoices = await get_user_invoices(db, user.id, limit=10)

    if not invoices:
        await update.message.reply_html("هنوز فاکتور یا تراکنشی برای شما ثبت نشده است.")
        return

    lines = ["📊 <b>گزارش آخرین فاکتورها و تراکنش‌ها:</b>\n"]
    for inv in invoices:
        toman = inv.final_amount // 10
        date_str = inv.created_at.strftime("%m/%d %H:%M")

        if inv.status == "PAID":
            status_badge = "🟢 موفق"
            payer = f"| واریزکننده: {inv.payer_name or 'ثبت شد'}"
        elif inv.status == "PENDING":
            status_badge = "🟡 در انتظار"
            payer = ""
        else:
            status_badge = "⚪ منقضی"
            payer = ""

        lines.append(f"#{inv.id} | {status_badge} | <code>{toman:,} تومان</code> {payer} ({date_str})")

    await update.message.reply_html("\n".join(lines))

def get_invoice_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧾 صدور فاکتور سریع$"), start_create_invoice_flow)],
        states={
            INVOICE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_amount_received)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False
    )
