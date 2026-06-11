from sqlalchemy import Column, Integer, BigInteger, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database.base import Base


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    name_ar = Column(String, nullable=True)          # Arabic display name
    icon_url = Column(String, nullable=True)          # Game icon from provider
    sort_order = Column(Integer, default=0)           # Manual sort order
    fc_game_id = Column(String, nullable=True)        # FazerCards game_id for validation
    # Admin-set category override. If NULL, the categoriser auto-detects from
    # the name. See services.game_categorizer.CATEGORIES for valid keys.
    category_key = Column(String, nullable=True)
    status = Column(Boolean, default=True)

    products = relationship("GameProduct", back_populates="game", cascade="all, delete-orphan")

    @property
    def display_name(self):
        return self.name_ar or self.name


class GameProduct(Base):
    __tablename__ = "game_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    name = Column(String, nullable=False)
    name_ar = Column(String, nullable=True)           # Arabic display name
    description = Column(Text, nullable=True)         # Product description
    currency = Column(String, default="USD")          # Currency from provider
    base_price = Column(Numeric(precision=10, scale=4), nullable=False)
    price = Column(Numeric(precision=10, scale=4), nullable=False)
    api_service_id = Column(String, nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    active = Column(Boolean, default=False)           # False = synced but not visible
    sort_order = Column(Integer, default=0)           # Manual sort order
    fields_json = Column(JSON, nullable=True)         # Required fields from provider e.g. [{"name":"playerID","label":"Player ID"}]
    min_quantity = Column(Integer, default=1)
    max_quantity = Column(Integer, default=1)
    region = Column(String, nullable=True)            # Region info from provider

    game = relationship("Game", back_populates="products")
    provider = relationship("Provider")

    @property
    def display_name(self):
        return self.name_ar or self.name


class GameOrder(Base):
    __tablename__ = "game_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)  # BigInteger for Telegram IDs
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("game_products.id"), nullable=False)
    account_id = Column(String, nullable=False)
    extra_data = Column(JSON, nullable=True)
    price = Column(Numeric(precision=10, scale=4), nullable=False)
    status = Column(String, default="pending")  # pending, processing, completed, canceled
    external_order_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")
    game = relationship("Game")
    product = relationship("GameProduct")
