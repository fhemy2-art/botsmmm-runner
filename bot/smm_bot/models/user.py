from sqlalchemy import Column, Integer, String, Numeric, DateTime, BigInteger, Boolean, Sequence
from sqlalchemy.sql import func
from database.base import Base

# Sequence for auto-incrementing account numbers (works on both SQLite & PG)
account_number_seq = Sequence('account_number_seq', start=1000, increment=1)


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    account_number = Column(Integer, unique=True, nullable=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    balance = Column(Numeric(12, 4), default=0)
    total_spent = Column(Numeric(12, 4), default=0)
    currency = Column(String, default="USD")
    language = Column(String, default="ar")
    vip_level = Column(Integer, default=0)
    referred_by = Column(BigInteger, nullable=True)
    referral_count = Column(Integer, default=0)
    referral_earnings = Column(Numeric(12, 4), default=0)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
