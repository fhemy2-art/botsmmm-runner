from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, BigInteger, Boolean
from sqlalchemy.sql import func
from database.base import Base
# NOTE: provider_attempts and last_provider_error columns are managed via
# the migration runner in database/session.py for backward compatibility.


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    link = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    charge = Column(Numeric(12, 6), nullable=False)
    status = Column(String, default="pending")
    external_order_id = Column(String, nullable=True)
    provider_id = Column(Integer, nullable=True)
    review_sent = Column(Boolean, default=False)
    # Stuck-order recovery instrumentation (see services.order_status).
    provider_attempts = Column(Integer, default=0)
    last_provider_error = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
