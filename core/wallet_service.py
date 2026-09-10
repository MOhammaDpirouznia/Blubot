import datetime
import logging
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User
from database.crud import modify_wallet_balance
import config

logger = logging.getLogger("wallet_service")

class WalletService:
    @staticmethod
    def calculate_commission(user: User, amount: int) -> Tuple[int, str]:
        """
        Calculates commission according to BluPal fee model:
        - Free during trial period (first 30 days or first 50 transactions)
        - Otherwise, percentage up to ceiling cap (e.g. 2% up to 35,000 Tomans = 350,000 Rials)
        Returns: (fee_amount_rials, reason_description)
        """
        now = datetime.datetime.utcnow()

        # Check free trial period
        if user.free_until and user.free_until > now:
            return 0, "طرح رایگان ماه اول (کارمزد ۰)"

        # Check free transaction quota
        if user.free_transactions_left > 0:
            return 0, f"تراکنش رایگان هدیه ({user.free_transactions_left} تراکنش باقی‌مانده)"

        # Standard BluPal calculation: fee = min(amount * fee_percent, fee_cap)
        rate = user.fee_percent / 100.0
        calculated_fee = int(amount * rate)
        final_fee = min(calculated_fee, user.fee_cap)

        return final_fee, f"کارمزد {user.fee_percent}% (سقف: {user.fee_cap:,} ریال)"

    @staticmethod
    async def process_invoice_commission(
        db: AsyncSession,
        user: User,
        invoice_id: int,
        amount: int
    ) -> Tuple[int, bool]:
        """
        Calculates and deducts commission from merchant's wallet.
        Returns: (fee_charged, is_low_balance_warning)
        """
        fee, reason = WalletService.calculate_commission(user, amount)

        # Decrement free transaction counter if applicable
        if fee == 0 and user.free_transactions_left > 0 and (not user.free_until or user.free_until <= datetime.datetime.utcnow()):
            user.free_transactions_left = max(0, user.free_transactions_left - 1)
            await db.commit()

        if fee > 0:
            desc = f"کارمزد فاکتور #{invoice_id} ({reason})"
            new_balance = await modify_wallet_balance(
                db=db,
                user_id=user.id,
                amount=-fee,
                tx_type="COMMISSION",
                description=desc,
                invoice_id=invoice_id
            )
            is_low_balance = new_balance < config.MIN_WALLET_BALANCE_ALERT
            logger.info(f"Deducted fee {fee} from user {user.id}. New balance: {new_balance}")
            return fee, is_low_balance

        return 0, user.wallet_balance < config.MIN_WALLET_BALANCE_ALERT

    @staticmethod
    async def top_up_wallet(
        db: AsyncSession,
        user_id: int,
        amount: int,
        description: str = "شارژ کیف پول"
    ) -> int:
        """Adds funds to merchant's prepaid wallet balance."""
        return await modify_wallet_balance(
            db=db,
            user_id=user_id,
            amount=amount,
            tx_type="DEPOSIT",
            description=description
        )
