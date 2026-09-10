import datetime
from typing import Optional
from fastapi import APIRouter, Header, Query, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from database.crud import (
    get_user_by_api_key,
    get_user_sessions,
    create_invoice,
    get_invoice_by_id,
    mark_invoice_paid,
    get_invoice_by_token
)
from database.models import User, Invoice
from core.matching_engine import MatchingEngine
from core.wallet_service import WalletService
from core.webhook_dispatcher import WebhookDispatcher
from api.schemas import (
    CreateInvoiceRequest,
    CreateInvoiceResponse,
    InvoiceStatusResponse,
    SimulateRequest,
    SimulateResponse
)
import config

router = APIRouter(prefix="/api/v1", tags=["Invoices"])

async def authenticate_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
) -> tuple[User, str]:
    token = x_api_key or api_key
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "message": "کلید API ارائه نشده است."}
        )

    auth = await get_user_by_api_key(db, token)
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "message": "کلید API نامعتبر است."}
        )

    return auth  # (User, mode: 'live' | 'sandbox')

@router.post("/invoices/create", response_model=CreateInvoiceResponse)
async def api_create_invoice(
    payload: CreateInvoiceRequest,
    auth: tuple[User, str] = Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_db)
):
    user, mode = auth

    # Check prepaid wallet balance (if negative more than buffer, block new invoices)
    if user.wallet_balance < -100000 and mode == "live":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "success": False,
                "error": "insufficient_wallet_balance",
                "message": "اعتبار کیف پول شما منفی است. لطفاً ابتدا حساب خود را در ربات تلگرام شارژ کنید."
            }
        )

    # Determine destination card number
    sessions = await get_user_sessions(db, user.id)
    target_card = None
    target_session_id = None

    if payload.card_number:
        clean_input = payload.card_number.replace("-", "").replace(" ", "")
        for s in sessions:
            if s.card_number == clean_input:
                target_card = clean_input
                target_session_id = s.id
                break
        if not target_card:
            # In sandbox mode, allow the custom card if requested
            if mode == "sandbox":
                target_card = clean_input
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"success": False, "error": "invalid_card", "message": "شماره کارت متعلق به حساب‌های فعال شما نیست."}
                )
    else:
        # Default to first active bank session
        active_sessions = [s for s in sessions if s.status == "ACTIVE"]
        if not active_sessions:
            if mode == "sandbox":
                target_card = "6219861012345678"
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"success": False, "error": "no_active_card", "message": "هیچ کارت یا نشست فعالی برای حساب شما ثبت نشده است."}
                )
        else:
            target_card = active_sessions[0].card_number
            target_session_id = active_sessions[0].id

    # Allocate random offset (e.g. +123 Rials)
    offset, final_amount = await MatchingEngine.allocate_unique_offset(db, target_card, payload.amount)

    # Calculate expiration time
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=config.INVOICE_TTL_MINUTES)

    # Create Invoice Record
    invoice = await create_invoice(
        db=db,
        user_id=user.id,
        card_number=target_card,
        base_amount=payload.amount,
        random_offset=offset,
        final_amount=final_amount,
        expires_at=expires_at,
        mode=mode,
        session_id=target_session_id
    )

    payment_link = f"{config.BASE_URL}/payment/{invoice.public_token}"
    if mode == "sandbox":
        payment_link = f"{config.BASE_URL}/sandbox/payment/{invoice.public_token}"

    return CreateInvoiceResponse(
        success=True,
        invoice_id=invoice.id,
        amount=invoice.base_amount,
        final_amount=invoice.final_amount,
        status=invoice.status,
        payment_link=payment_link,
        card_number=invoice.card_number,
        mode=invoice.mode,
        expires_at=invoice.expires_at.isoformat() + "+03:30"
    )

@router.get("/invoices/{invoice_id}", response_model=InvoiceStatusResponse)
async def api_get_invoice_status(
    invoice_id: int,
    auth: tuple[User, str] = Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_db)
):
    user, mode = auth
    invoice = await get_invoice_by_id(db, invoice_id)

    if not invoice or invoice.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "error": "not_found", "message": "فاکتور مورد نظر یافت نشد."}
        )

    return InvoiceStatusResponse(
        success=True,
        invoice_id=invoice.id,
        status=invoice.status,
        transaction_id=invoice.id if invoice.status == "PAID" else None,
        amount=invoice.base_amount,
        final_amount=invoice.final_amount,
        mode=invoice.mode,
        expires_at=invoice.expires_at.isoformat() if invoice.expires_at else None,
        payer_name=invoice.payer_name,
        payer_card=invoice.payer_card,
        payer_bank_name=invoice.payer_bank_name
    )

@router.post("/sandbox/invoices/{invoice_id}/simulate", response_model=SimulateResponse)
async def api_simulate_sandbox_payment(
    invoice_id: int,
    payload: SimulateRequest,
    auth: tuple[User, str] = Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_db)
):
    user, mode = auth
    if mode != "sandbox":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "mode_mismatch", "message": "شبیه‌سازی فقط با کلید آزمایشی (blu_test_...) مجاز است."}
        )

    invoice = await get_invoice_by_id(db, invoice_id)
    if not invoice or invoice.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "error": "not_found", "message": "فاکتور یافت نشد."}
        )

    if invoice.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "invalid_state", "message": f"وضعیت فاکتور {invoice.status} است و امکان تغییر ندارد."}
        )

    scenario = (payload.scenario or "success").lower()

    if scenario == "success":
        # Simulate payment
        fee_charged, _ = await WalletService.process_invoice_commission(
            db=db,
            user=user,
            invoice_id=invoice.id,
            amount=invoice.base_amount
        )
        paid = await mark_invoice_paid(
            db=db,
            invoice_id=invoice.id,
            payer_name="علی رضایی (تست)",
            payer_card="6037991234567890",
            payer_bank="بانک ملی",
            bank_track_id="TEST_REF_123456",
            fee_charged=fee_charged
        )

        if user.webhook_url:
            await WebhookDispatcher.dispatch(paid, user.webhook_url)

        return SimulateResponse(
            success=True,
            status="PAID",
            invoice_id=invoice.id,
            transaction_id=invoice.id
        )

    elif scenario == "expire":
        invoice.status = "EXPIRED"
        await db.commit()
        return SimulateResponse(success=True, status="EXPIRED", invoice_id=invoice.id)

    elif scenario == "cancel":
        invoice.status = "CANCELED"
        await db.commit()
        return SimulateResponse(success=True, status="CANCELED", invoice_id=invoice.id)

    elif scenario == "wrong_amount":
        # Remains pending
        return SimulateResponse(success=True, status="PENDING", invoice_id=invoice.id)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "invalid_scenario", "message": "سناریو نامعتبر است."}
        )

# Public polling endpoint for payment checkout page
@router.get("/payment/check/{token}")
async def check_payment_status(token: str, db: AsyncSession = Depends(get_db)):
    invoice = await get_invoice_by_token(db, token)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        "status": invoice.status,
        "amount": invoice.base_amount,
        "final_amount": invoice.final_amount,
        "payer_name": invoice.payer_name
    }
