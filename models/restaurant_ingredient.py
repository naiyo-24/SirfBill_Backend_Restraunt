import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantIngredientCategory(Base):
    """
    Ingredient storage category & zone:
    e.g. Dry & Grain Pantry (Ambient Store Shelf A-C), Dairy & Cheese (Walk-in Chiller 2-4°C).
    Guarantees strict tenant and branch (outlet) level isolation.
    """
    __tablename__ = "restaurant_ingredient_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=True, index=True) # e.g. DRY, DAIRY, MEAT, PRODUCE, SPICE, BAR
    storage_zone_temp = Column(String(150), nullable=True) # e.g. "Ambient Store (Shelf A-C)", "Walk-in Chiller (2°C - 4°C)"
    color_code = Column(String(30), nullable=True) # e.g. "#f59e0b" for UI badges/cards
    icon = Column(String(50), nullable=True) # e.g. "box", "snowflake", emoji
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet", back_populates="ingredient_categories")
    ingredients = relationship("RestaurantIngredient", back_populates="category", cascade="all, delete-orphan")


class RestaurantIngredient(Base):
    """
    Ingredient master: e.g. Chicken (KG), Basmati Rice (KG), Cooking Oil (L), Cheese (G).
    Isolated strictly by outlet_id and tenant_id.
    """
    __tablename__ = "restaurant_ingredients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredient_categories.id", ondelete="SET NULL"), nullable=True, index=True)

    name = Column(String(150), nullable=False)
    sku = Column(String(50), nullable=True, index=True)
    unit = Column(String(20), nullable=False) # Recipe UOM or default unit: KG, G, L, ML, PCS
    storage_zone = Column(String(100), nullable=True) # Specific shelf/bin if detailed
    storage_location = Column(String(100), nullable=True) # Storage location / shelf
    current_stock = Column(Numeric(12, 3), default=0.000, nullable=False)
    reorder_level = Column(Numeric(12, 3), default=5.000, nullable=False)
    cost_per_unit = Column(Numeric(10, 2), default=0.00, nullable=False)
    
    # Complete Restaurant Inventory Master Fields
    purchase_uom = Column(String(20), default="KG", nullable=True)
    recipe_uom = Column(String(20), default="G", nullable=True)
    uom_conversion_factor = Column(Numeric(12, 4), default=1.0000, nullable=True)
    min_par_level = Column(Numeric(12, 3), default=0.000, nullable=True)
    ideal_par_level = Column(Numeric(12, 3), default=0.000, nullable=True)
    cost_per_purchase_unit = Column(Numeric(10, 2), default=0.00, nullable=True)
    primary_supplier_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    is_perishable = Column(Boolean, default=False, nullable=False)
    shelf_life_days = Column(Integer, nullable=True)
    last_restocked_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    image_url = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet", back_populates="ingredients")
    category = relationship("RestaurantIngredientCategory", back_populates="ingredients")
    supplier = relationship("RestaurantSupplier")
    ledger_entries = relationship("RestaurantStockLedger", back_populates="ingredient")

