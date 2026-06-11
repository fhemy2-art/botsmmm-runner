from sqlalchemy import Column, Integer, String, Boolean
from database.base import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    api_url = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    status = Column(Boolean, default=True)
    provider_type = Column(String, default="smm")  # "smm" or "game"
