from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from database.base import Base


class Moderator(Base):
    __tablename__ = "moderators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    added_by = Column(BigInteger, nullable=True)
    is_active = Column(Boolean, default=True)
    # Permissions flags
    can_services = Column(Boolean, default=False)     # ادارة الخدمات
    can_users = Column(Boolean, default=False)         # ادارة المستخدمين
    can_balance = Column(Boolean, default=False)       # شحن/خصم الرصيد
    can_broadcast = Column(Boolean, default=False)     # الاشعارات الجماعية
    can_orders = Column(Boolean, default=False)        # ادارة الطلبات
    can_providers = Column(Boolean, default=False)     # ادارة المزودين
    can_stats = Column(Boolean, default=False)         # الاحصائيات
    can_games = Column(Boolean, default=False)         # ادارة الالعاب
    created_at = Column(DateTime, server_default=func.now())
