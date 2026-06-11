from sqlalchemy import Column, Integer, String, Numeric, DateTime, BigInteger, Boolean
from sqlalchemy.sql import func
from database.base import Base


class ReadyAccount(Base):
    __tablename__ = "ready_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_type = Column(String, nullable=False)       # "whatsapp" or "telegram"
    country = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    description = Column(String, nullable=True)
    price = Column(Numeric(12, 4), nullable=False)
    is_sold = Column(Boolean, default=False)
    buyer_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    sold_at = Column(DateTime, nullable=True)
