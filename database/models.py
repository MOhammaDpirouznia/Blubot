import datetime
import uuid
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean,
    DateTime, ForeignKey, Text, Index
)
from sqlalchemy.orm import relationship
from database.connection import Base
import config

def generate_key(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String(100), nullable=True)
    first_name = Column(String(150), nullable=True)
    phone_number = Column(String(30), nullable=True)

    # Prepaid Wallet Balance (in Rials)
    wallet_balance = Column(BigInteger, default=0, nullable=False)

    # Dynamic Commission Settings
    fee_percent = Column(Float, default=config.DEFAULT_FEE_PERCENT, nullable=False)  # e.g. 2.0%
    fee_cap = Column(BigInteger, default=config.DEFAULT_FEE_CAP, nullable=False)      # e.g. 350,000 Rials
    free_until = Column(DateTime, nullable=True)                                     # Free trial expiration
    free_transactions_left = Column(Integer, default=config.FREE_TRIAL_TRANSACTIONS, nullable=False)

    # API Keys & Webhook
    api_key_live = Column(String(80), unique=True, index=True, nullable=False)
    api_key_test = Column(String(80), unique=True, index=True, nullable=False)
    webhook_url = Column(String(500), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    sessions = relationship("BankSession", back_populates="user", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="user", cascade="all, delete-orphan")
    wallet_logs = relationship("WalletLedger", back_populates="user", cascade="all, delete-orphan")

class BankSession(Base):
    __tablename__ = "bank_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    phone_number = Column(String(30), nullable=False)
    card_number = Column(String(16), index=True, nullable=False)
    sheba_number = Column(String(34), nullable=True)
    account_name = Column(String(200), nullable=True)

    # Encrypted payload containing access_token, refresh_token, device_id, etc.
    encrypted_tokens = Column(Text, nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False)  # ACTIVE, EXPIRED, PAUSED, ERROR

    last_balance = Column(BigInteger, default=0, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="sessions")
    invoices = relationship("Invoice", back_populates="session")

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("bank_sessions.id", ondelete="SET NULL"), nullable=True)

    card_number = Column(String(16), index=True, nullable=False)
    base_amount = Column(BigInteger, nullable=False)     # Requested amount in Rials
    random_offset = Column(Integer, nullable=False)     # Random offset e.g. 123 Rials
    final_amount = Column(BigInteger, index=True, nullable=False)  # base_amount + random_offset

    status = Column(String(20), default="PENDING", index=True, nullable=False)  # PENDING, PAID, EXPIRED, CANCELED
    mode = Column(String(10), default="live", nullable=False)                   # live, sandbox

    # Payer Info (Filled upon receipt)
    payer_name = Column(String(200), nullable=True)
    payer_card = Column(String(30), nullable=True)       # Card number or Sheba
    payer_bank_name = Column(String(100), nullable=True)
    bank_track_id = Column(String(100), nullable=True)   # Reference or transaction ID from bank

    # Fee charged from user wallet
    fee_charged = Column(BigInteger, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="invoices")
    session = relationship("BankSession", back_populates="invoices")
    deliveries = relationship("WebhookDelivery", back_populates="invoice", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_card_final_amount_status", "card_number", "final_amount", "status"),
    )

class WalletLedger(Base):
    __tablename__ = "wallet_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)

    type = Column(String(20), nullable=False)  # DEPOSIT, COMMISSION, GIFT, REFUND
    amount = Column(BigInteger, nullable=False)  # Positive or Negative in Rials
    balance_after = Column(BigInteger, nullable=False)
    description = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="wallet_logs")

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(500), nullable=False)
    payload = Column(Text, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    attempts = Column(Integer, default=1, nullable=False)
    is_success = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    last_attempt_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    invoice = relationship("Invoice", back_populates="deliveries")
