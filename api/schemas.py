from typing import Optional
from pydantic import BaseModel, Field

class CreateInvoiceRequest(BaseModel):
    amount: int = Field(..., ge=100000, description="Amount in Rials (Minimum 100,000 Rials = 10,000 Tomans)")
    card_number: Optional[str] = Field(None, description="Optional 16-digit card number belonging to user")

class CreateInvoiceResponse(BaseModel):
    success: bool
    invoice_id: int
    amount: int
    final_amount: int
    status: str
    payment_link: str
    card_number: str
    mode: str
    expires_at: Optional[str] = None

class InvoiceStatusResponse(BaseModel):
    success: bool
    invoice_id: int
    status: str
    transaction_id: Optional[int] = None
    amount: int
    final_amount: int
    mode: str
    expires_at: Optional[str] = None
    payer_name: Optional[str] = None
    payer_card: Optional[str] = None
    payer_bank_name: Optional[str] = None

class SimulateRequest(BaseModel):
    scenario: Optional[str] = Field("success", description="Scenario: success, wrong_amount, expire, cancel")

class SimulateResponse(BaseModel):
    success: bool
    status: str
    invoice_id: int
    transaction_id: Optional[int] = None

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: Optional[str] = None
