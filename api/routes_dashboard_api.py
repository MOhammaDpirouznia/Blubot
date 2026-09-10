import datetime
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from database.connection import get_db
from database.models import User, BankSession
from database.crud import (
    get_or_create_user,
    get_user_by_api_key,
    update_user_webhook,
    regenerate_api_keys,
    create_invoice,
    get_user_sessions,
    modify_wallet_balance
)
from core.matching_engine import MatchingEngine
from api.routes_web import get_session_user_id

router = APIRouter(prefix="/api/v1", tags=["Dashboard AJAX"])

class LoginRequest(BaseModel):
    identifier: str
    api_key: str | None = None

class WebhookRequest(BaseModel):
    webhook_url: str

class QuickInvoiceRequest(BaseModel):
    amount: int

class TopupRequest(BaseModel):
    amount: int

class FeeUpdateRequest(BaseModel):
    fee_percent: float
    fee_cap: int

@router.post("/auth/login")
async def web_login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = None

    # Try API Key authentication if provided
    if payload.api_key:
        auth = await get_user_by_api_key(db, payload.api_key.strip())
        if auth:
            user = auth[0]

    # Try Identifier (Telegram ID or Phone)
    if not user and payload.identifier:
        clean_id = "".join([c for c in payload.identifier if c.isdigit()])
        if clean_id:
            tg_id = int(clean_id)
            user, _ = await get_or_create_user(db, telegram_id=tg_id, username=f"user_{tg_id}", first_name="پذیرنده")

    if not user:
        return JSONResponse({"success": False, "message": "اطلاعات ورود نامعتبر است."}, status_code=400)

    res = JSONResponse({"success": True, "user_id": user.id})
    res.set_cookie(
        key="blupal_user_id",
        value=str(user.id),
        httponly=True,
        max_age=86400 * 30,  # 30 days
        samesite="lax"
    )
    return res

@router.post("/dashboard/webhook")
async def update_webhook(payload: WebhookRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await update_user_webhook(db, user_id, payload.webhook_url)
    return {"success": True, "message": "وب‌هوک با موفقیت ذخیره شد."}

@router.post("/dashboard/webhook/test")
async def test_webhook_endpoint(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    if not user or not user.webhook_url:
        return {"success": False, "message": "ابتدا باید آدرس وب‌هوک را تنظیم کنید."}

    test_payload = {
        "success": True,
        "event": "payment.completed",
        "invoice_id": 9999,
        "status": "PAID",
        "amount": 1000000,
        "final_amount": 1000243,
        "mode": "test",
        "payer_name": "تست وب‌هوک داشبورد",
        "payer_card": "6037991234567890",
        "payer_bank_name": "بانک ملی"
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(user.webhook_url, json=test_payload)
            return {
                "success": resp.status_code == 200,
                "message": f"پاسخ سرور: HTTP {resp.status_code} ({resp.text[:100]})"
            }
    except Exception as e:
        return {"success": False, "message": f"خطا در ارسال به وب‌هوک: {str(e)}"}

@router.post("/dashboard/keys/regenerate")
async def regen_keys(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    live, test = await regenerate_api_keys(db, user_id)
    return {"success": True, "api_key_live": live, "api_key_test": test}

@router.post("/dashboard/invoices/create")
async def create_quick_invoice(payload: QuickInvoiceRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = await db.get(User, user_id)
    sessions = await get_user_sessions(db, user_id)

    target_card = sessions[0].card_number if sessions else "6219861012345678"
    session_id = sessions[0].id if sessions else None

    offset, final_amount = await MatchingEngine.allocate_unique_offset(db, target_card, payload.amount)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=config.INVOICE_TTL_MINUTES)

    inv = await create_invoice(
        db=db,
        user_id=user.id,
        card_number=target_card,
        base_amount=payload.amount,
        random_offset=offset,
        final_amount=final_amount,
        expires_at=expires_at,
        mode="live",
        session_id=session_id
    )

    return {
        "success": True,
        "invoice_id": inv.id,
        "amount": inv.base_amount,
        "final_amount": inv.final_amount,
        "payment_link": f"{config.BASE_URL}/payment/{inv.public_token}"
    }

@router.post("/dashboard/wallet/topup")
async def topup_wallet(payload: TopupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = get_session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    new_balance = await modify_wallet_balance(
        db=db,
        user_id=user_id,
        amount=payload.amount,
        tx_type="DEPOSIT",
        description=f"شارژ کیف پول از داشبورد وب ({payload.amount // 10:,} تومان)"
    )
    return {"success": True, "new_balance": new_balance}

@router.post("/admin/user/{user_id}/fee")
async def update_user_fee(user_id: int, payload: FeeUpdateRequest, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.fee_percent = payload.fee_percent
    user.fee_cap = payload.fee_cap
    await db.commit()
    return {"success": True, "message": "Fee updated successfully"}
