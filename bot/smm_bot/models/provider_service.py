from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Boolean, Text
from database.base import Base


class ProviderService(Base):
    __tablename__ = "provider_services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    external_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    type = Column(String, nullable=True)
    rate = Column(Numeric(20, 8), nullable=True)  # was (12,6) — caused overflow
    min = Column(Integer, nullable=True)
    max = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    refill = Column(Boolean, nullable=True)
    cancel = Column(Boolean, nullable=True)
