import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantMenuCategory(Base):
    __tablename__ = "restaurant_menu_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon_emoji = Column(String(50), default="🍽️", nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet", back_populates="categories")
    items = relationship("RestaurantMenuItem", back_populates="category", cascade="all, delete-orphan")


class RestaurantMenuItem(Base):
    __tablename__ = "restaurant_menu_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_menu_categories.id", ondelete="SET NULL"), nullable=True, index=True)

    name = Column(String(150), nullable=False)
    short_code = Column(String(30), nullable=True, index=True) # E.g. "CB" for Chicken Biryani
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)

    # Dietary & Station tags
    item_type = Column(String(20), default="NON_VEG", nullable=False) # VEG, NON_VEG, EGG, VEGAN
    prep_station = Column(String(50), default="KITCHEN", nullable=False) # KITCHEN, BAR, DESSERT, PIZZA, PANTRY
    tax_rate = Column(Numeric(5, 2), default=5.00, nullable=False) # 5.00% GST default for restaurants
    price = Column(Numeric(10, 2), default=0.00, nullable=True) # Direct base price
    takeaway_price = Column(Numeric(10, 2), nullable=True)
    delivery_price = Column(Numeric(10, 2), nullable=True)
    variant_prices = Column(JSON, default=list, nullable=True)
    badge = Column(String(50), nullable=True) # E.g. Popular, Bestseller, Chef Special

    is_available = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet", back_populates="items")
    category = relationship("RestaurantMenuCategory", back_populates="items")

    @property
    def prices(self):
        """Synthesized price list for API backward compatibility."""
        return [
            {
                "id": self.id,
                "item_id": self.id,
                "variant_name": "Standard",
                "channel": "DEFAULT",
                "price": self.price or 0.00,
                "created_at": self.created_at
            }
        ]
