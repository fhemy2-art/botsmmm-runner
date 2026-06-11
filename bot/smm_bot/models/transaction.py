from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, BigInteger, Index
from sqlalchemy.sql import func
from database.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(12, 4), nullable=False)
    description = Column(String, nullable=True)
    # External reference for idempotency (e.g. Telegram Stars charge id, Binance trade no).
    # Unique to prevent double-credit if the same payment update is delivered twice.
    external_ref = Column(String, nullable=True, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
