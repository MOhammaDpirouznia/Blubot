import random
import datetime
import logging
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from database.crud import (
    get_active_offsets_for_card,
    find_pending_invoice_by_amount,
    mark_invoice_paid,
    expire_stale_invoices
)
from database.models import Invoice, User
from blubank.client import BluTransaction
from core.wallet_service import WalletService
from core.webhook_dispatcher import WebhookDispatcher
import config

logger = logging.getLogger("matching_engine")

class MatchingEngine:
    @staticmethod
    async def allocate_unique_offset(
        db: AsyncSession,
        card_number: str,
        base_amount: int
    ) -> Tuple[int, int]:
        """
        Generates a unique random 3-digit offset (100 to 999) for this card
        so that no two active pending invoices share the same final_amount.
        Returns: (random_offset, final_amount)
        """
        active_offsets = await get_active_offsets_for_card(db, card_number)

        # Available offsets from 100 to 999
        available = [i for i in range(100, 1000) if i not in active_offsets]
        if not available:
            # Fallback to 4 digits if all 900 3-digit slots are busy on the card
            available = [i for i in range(1000, 5000) if i not in active_offsets]

        offset = random.choice(available)
        final_amount = base_amount + offset
        return offset, final_amount

    @staticmethod
    async def match_and_process_deposit(
        db: AsyncSession,
        card_number: str,
        tx: BluTransaction
    ) -> Optional[Tuple[Invoice, int, bool]]:
        """
        Processes a bank deposit transaction:
        1. Checks if it matches any active pending invoice.
        2. Deducts fee from merchant wallet.
        3. Marks invoice as PAID.
        4. Dispatches webhook.
        Returns: (Invoice, fee_charged, is_low_balance) or None if no match.
        """
        if not tx.is_deposit:
            return None

        # Clean card number formatting
        clean_card = card_number.replace("-", "").replace(" ", "").strip()

        # Find matching invoice by final amount
        invoice = await find_pending_invoice_by_amount(db, clean_card, tx.amount)
        if not invoice:
            return None

        user = await db.get(User, invoice.user_id)
        if not user:
            return None

        # Calculate and deduct fee
        fee_charged, is_low_balance = await WalletService.process_invoice_commission(
            db=db,
            user=user,
            invoice_id=invoice.id,
            amount=invoice.base_amount
        )

        # Update invoice to PAID
        paid_invoice = await mark_invoice_paid(
            db=db,
            invoice_id=invoice.id,
            payer_name=tx.payer_name,
            payer_card=tx.payer_card,
            payer_bank=tx.payer_bank,
            bank_track_id=tx.tracking_number,
            fee_charged=fee_charged
        )

        logger.info(
            f"MATCHED Invoice #{invoice.id}: Amount={tx.amount}, Payer='{tx.payer_name}', Fee={fee_charged}"
        )

        # Send Webhook if configured
        if user.webhook_url:
            await WebhookDispatcher.dispatch(paid_invoice, user.webhook_url)

        return paid_invoice, fee_charged, is_low_balance

    @staticmethod
    async def clean_expired(db: AsyncSession) -> int:
        """Cleans up and expires outdated pending invoices."""
        count = await expire_stale_invoices(db)
        if count > 0:
            logger.info(f"Expired {count} pending invoices.")
        return count
