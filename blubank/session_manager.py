import datetime
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import BankSession
from blubank.crypto import decrypt_session_data, encrypt_session_data
from blubank.client import BluBankClient

logger = logging.getLogger("session_manager")

class SessionManager:
    @staticmethod
    def get_client(session: BankSession) -> BluBankClient:
        """Instantiates a BluBankClient using encrypted session credentials."""
        try:
            tokens = decrypt_session_data(session.encrypted_tokens)
            return BluBankClient(
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                device_id=tokens.get("device_id"),
                cookies=tokens.get("cookies", {})
            )
        except Exception as e:
            logger.error(f"Failed to decrypt bank session {session.id}: {e}")
            return BluBankClient()

    @staticmethod
    async def refresh_and_validate(db: AsyncSession, session: BankSession) -> bool:
        """Validates that the session is still active with BluBank."""
        client = SessionManager.get_client(session)
        cards_info = await client.get_cards_and_accounts()
        if cards_info and "cards" in cards_info and len(cards_info["cards"]) > 0:
            card = cards_info["cards"][0]
            session.last_balance = card.get("balance", session.last_balance)
            session.last_sync_at = datetime.datetime.utcnow()
            session.status = "ACTIVE"
            await db.commit()
            return True
        else:
            session.status = "EXPIRED"
            await db.commit()
            return False
