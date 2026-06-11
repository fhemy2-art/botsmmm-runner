from sqlalchemy import Column, Integer, String, Numeric, Boolean, ForeignKey
from database.base import Base


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    description_ar = Column(String, nullable=True)
    price_per_1000 = Column(Numeric(12, 6), nullable=False)
    speed = Column(String, nullable=True)
    quality = Column(String, nullable=True)
    guarantee_days = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    provider_service_id = Column(Integer, ForeignKey("provider_services.id"), nullable=True)
