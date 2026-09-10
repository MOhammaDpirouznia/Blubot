import asyncio
import logging
import httpx
from database.connection import AsyncSessionLocal
from database.crud import log_webhook_delivery
from database.models import Invoice

logger = logging.getLogger("webhook_dispatcher")

class WebhookDispatcher:
    @staticmethod
    async def dispatch(invoice: Invoice, webhook_url: str):
        """Dispatches payment.completed webhook in the background with retry logic."""
        if not webhook_url:
            return

        payload = {
            "success": True,
            "event": "payment.completed",
            "invoice_id": invoice.id,
            "status": "PAID",
            "amount": invoice.base_amount,
            "final_amount": invoice.final_amount,
            "mode": invoice.mode,
            "payer_name": invoice.payer_name,
            "payer_card": invoice.payer_card,
            "payer_bank_name": invoice.payer_bank_name
        }

        asyncio.create_task(WebhookDispatcher._send_with_retries(invoice.id, webhook_url, payload))

    @staticmethod
    async def _send_with_retries(invoice_id: int, url: str, payload: dict):
        delays = [0, 10, 30, 60]  # Initial attempt + 3 retries
        success = False

        for attempt, delay in enumerate(delays, 1):
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                    status_code = resp.status_code
                    body = resp.text

                    if status_code == 200:
                        success = True
                        logger.info(f"Webhook delivered for invoice {invoice_id} on attempt {attempt}")
                        await WebhookDispatcher._save_log(invoice_id, url, payload, status_code, body, attempt, True)
                        break
                    else:
                        logger.warning(f"Webhook HTTP {status_code} for invoice {invoice_id} on attempt {attempt}")
            except Exception as e:
                status_code = 0
                body = str(e)
                logger.warning(f"Webhook error for invoice {invoice_id} on attempt {attempt}: {e}")

            await WebhookDispatcher._save_log(invoice_id, url, payload, status_code, body, attempt, False)

    @staticmethod
    async def _save_log(invoice_id: int, url: str, payload: dict, status_code: int, body: str, attempt: int, success: bool):
        try:
            async with AsyncSessionLocal() as db:
                await log_webhook_delivery(
                    db=db,
                    invoice_id=invoice_id,
                    url=url,
                    payload=payload,
                    status_code=status_code,
                    response_body=body,
                    attempts=attempt,
                    is_success=success
                )
        except Exception as e:
            logger.error(f"Failed to save webhook delivery log: {e}")
