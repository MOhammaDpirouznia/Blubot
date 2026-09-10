import datetime
import json
import uuid
from typing import Optional, List, Tuple
from sqlalchemy import select, update, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User, BankSession, Invoice, WalletLedger, WebhookDelivery, generate_key
import config

# --- USER OPERATIONS ---

async def get_or_create_user(
    db: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None
) -> Tuple[User, bool]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        # Update username/first_name if changed
        if username and user.username != username:
            user.username = username
        if first_name and user.first_name != first_name:
            user.first_name = first_name
        await db.commit()
        await db.refresh(user)
        return user, False

    # Create new user with 30-day free trial
    free_until = datetime.datetime.utcnow() + datetime.timedelta(days=config.FREE_TRIAL_DAYS)
    new_user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        wallet_balance=0,
        fee_percent=config.DEFAULT_FEE_PERCENT,
        fee_cap=config.DEFAULT_FEE_CAP,
        free_until=free_until,
        free_transactions_left=config.FREE_TRIAL_TRANSACTIONS,
        api_key_live=generate_key("blu_live"),
        api_key_test=generate_key("blu_test"),
        is_active=True
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user, True

async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> Optional[User]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_by_api_key(db: AsyncSession, api_key: str) -> Optional[Tuple[User, str]]:
    """Returns (User, 'live') or (User, 'sandbox') if key matches."""
    if api_key.startswith("blu_live_"):
        stmt = select(User).where(User.api_key_live == api_key)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if user:
            return user, "live"
    elif api_key.startswith("blu_test_"):
        stmt = select(User).where(User.api_key_test == api_key)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if user:
            return user, "sandbox"
    return None

async def update_user_webhook(db: AsyncSession, user_id: int, webhook_url: str) -> None:
    stmt = update(User).where(User.id == user_id).values(webhook_url=webhook_url)
    await db.execute(stmt)
    await db.commit()

async def regenerate_api_keys(db: AsyncSession, user_id: int) -> Tuple[str, str]:
    new_live = generate_key("blu_live")
    new_test = generate_key("blu_test")
    stmt = update(User).where(User.id == user_id).values(
        api_key_live=new_live,
        api_key_test=new_test
    )
    await db.execute(stmt)
    await db.commit()
    return new_live, new_test

# --- WALLET OPERATIONS ---

async def modify_wallet_balance(
    db: AsyncSession,
    user_id: int,
    amount: int,
    tx_type: str,
    description: str,
    invoice_id: Optional[int] = None
) -> int:
    """Modifies user's wallet balance and records an immutable ledger record."""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    new_balance = user.wallet_balance + amount
    user.wallet_balance = new_balance

    ledger_entry = WalletLedger(
        user_id=user_id,
        invoice_id=invoice_id,
        type=tx_type,
        amount=amount,
        balance_after=new_balance,
        description=description,
        created_at=datetime.datetime.utcnow()
    )
    db.add(ledger_entry)
    await db.commit()
    return new_balance

async def get_user_wallet_history(db: AsyncSession, user_id: int, limit: int = 20) -> List[WalletLedger]:
    stmt = select(WalletLedger).where(WalletLedger.user_id == user_id).order_by(desc(WalletLedger.id)).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())

# --- BANK SESSION OPERATIONS ---

async def save_bank_session(
    db: AsyncSession,
    user_id: int,
    phone_number: str,
    card_number: str,
    encrypted_tokens: str,
    sheba_number: Optional[str] = None,
    account_name: Optional[str] = None
) -> BankSession:
    # Check if a session already exists for this card
    stmt = select(BankSession).where(
        and_(BankSession.user_id == user_id, BankSession.card_number == card_number)
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if session:
        session.encrypted_tokens = encrypted_tokens
        session.phone_number = phone_number
        session.sheba_number = sheba_number or session.sheba_number
        session.account_name = account_name or session.account_name
        session.status = "ACTIVE"
        session.last_sync_at = datetime.datetime.utcnow()
    else:
        session = BankSession(
            user_id=user_id,
            phone_number=phone_number,
            card_number=card_number,
            sheba_number=sheba_number,
            account_name=account_name,
            encrypted_tokens=encrypted_tokens,
            status="ACTIVE",
            created_at=datetime.datetime.utcnow(),
            last_sync_at=datetime.datetime.utcnow()
        )
        db.add(session)

    await db.commit()
    await db.refresh(session)
    return session

async def get_user_sessions(db: AsyncSession, user_id: int) -> List[BankSession]:
    stmt = select(BankSession).where(BankSession.user_id == user_id)
    res = await db.execute(stmt)
    return list(res.scalars().all())

async def get_all_active_sessions(db: AsyncSession) -> List[BankSession]:
    stmt = select(BankSession).where(BankSession.status == "ACTIVE")
    res = await db.execute(stmt)
    return list(res.scalars().all())

async def get_session_by_card(db: AsyncSession, card_number: str) -> Optional[BankSession]:
    stmt = select(BankSession).where(
        and_(BankSession.card_number == card_number, BankSession.status == "ACTIVE")
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def delete_session(db: AsyncSession, session_id: int) -> bool:
    session = await db.get(BankSession, session_id)
    if session:
        await db.delete(session)
        await db.commit()
        return True
    return False

# --- INVOICE OPERATIONS ---

async def create_invoice(
    db: AsyncSession,
    user_id: int,
    card_number: str,
    base_amount: int,
    random_offset: int,
    final_amount: int,
    expires_at: datetime.datetime,
    mode: str = "live",
    session_id: Optional[int] = None
) -> Invoice:
    public_token = uuid.uuid4().hex
    invoice = Invoice(
        public_token=public_token,
        user_id=user_id,
        session_id=session_id,
        card_number=card_number,
        base_amount=base_amount,
        random_offset=random_offset,
        final_amount=final_amount,
        status="PENDING",
        mode=mode,
        expires_at=expires_at,
        created_at=datetime.datetime.utcnow()
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice

async def get_invoice_by_id(db: AsyncSession, invoice_id: int) -> Optional[Invoice]:
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def get_invoice_by_token(db: AsyncSession, token: str) -> Optional[Invoice]:
    stmt = select(Invoice).where(Invoice.public_token == token)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def get_active_offsets_for_card(db: AsyncSession, card_number: str) -> set:
    """Returns all random offsets of currently active PENDING invoices for this card."""
    now = datetime.datetime.utcnow()
    stmt = select(Invoice.random_offset).where(
        and_(
            Invoice.card_number == card_number,
            Invoice.status == "PENDING",
            Invoice.expires_at > now
        )
    )
    res = await db.execute(stmt)
    return set(res.scalars().all())

async def find_pending_invoice_by_amount(
    db: AsyncSession,
    card_number: str,
    amount: int
) -> Optional[Invoice]:
    """Finds a pending invoice matching the exact received final_amount on this card."""
    now = datetime.datetime.utcnow()
    stmt = select(Invoice).where(
        and_(
            Invoice.card_number == card_number,
            Invoice.final_amount == amount,
            Invoice.status == "PENDING",
            Invoice.expires_at > now
        )
    ).order_by(Invoice.id.desc())
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def mark_invoice_paid(
    db: AsyncSession,
    invoice_id: int,
    payer_name: Optional[str] = None,
    payer_card: Optional[str] = None,
    payer_bank: Optional[str] = None,
    bank_track_id: Optional[str] = None,
    fee_charged: int = 0
) -> Optional[Invoice]:
    invoice = await db.get(Invoice, invoice_id)
    if not invoice or invoice.status != "PENDING":
        return None

    invoice.status = "PAID"
    invoice.payer_name = payer_name
    invoice.payer_card = payer_card
    invoice.payer_bank_name = payer_bank
    invoice.bank_track_id = bank_track_id
    invoice.fee_charged = fee_charged
    invoice.paid_at = datetime.datetime.utcnow()

    await db.commit()
    await db.refresh(invoice)
    return invoice

async def expire_stale_invoices(db: AsyncSession) -> int:
    """Marks pending invoices past their expiration as EXPIRED."""
    now = datetime.datetime.utcnow()
    stmt = (
        update(Invoice)
        .where(and_(Invoice.status == "PENDING", Invoice.expires_at <= now))
        .values(status="EXPIRED")
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount

async def get_user_invoices(db: AsyncSession, user_id: int, limit: int = 15) -> List[Invoice]:
    stmt = select(Invoice).where(Invoice.user_id == user_id).order_by(desc(Invoice.id)).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())

# --- WEBHOOK DELIVERIES ---

async def log_webhook_delivery(
    db: AsyncSession,
    invoice_id: int,
    url: str,
    payload: dict,
    status_code: Optional[int],
    response_body: Optional[str],
    attempts: int,
    is_success: bool
) -> WebhookDelivery:
    log = WebhookDelivery(
        invoice_id=invoice_id,
        url=url,
        payload=json.dumps(payload, ensure_ascii=False),
        status_code=status_code,
        response_body=response_body[:1000] if response_body else None,
        attempts=attempts,
        is_success=is_success,
        created_at=datetime.datetime.utcnow(),
        last_attempt_at=datetime.datetime.utcnow()
    )
    db.add(log)
    await db.commit()
    return log
