import uuid
from decimal import Decimal
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RecipeLineCompat:
    def __init__(self, ingredient_id, quantity_required, unit):
        self.ingredient_id = ingredient_id
        self.quantity_required = Decimal(str(quantity_required))
        self.unit = unit
        self._ingredient = None

    @property
    def ingredient(self):
        if self._ingredient is None and self.ingredient_id:
            from models.database import SessionLocal
            from models.restaurant_ingredient import RestaurantIngredient
            db = SessionLocal()
            try:
                self._ingredient = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == self.ingredient_id).first()
            finally:
                db.close()
        return self._ingredient

class RestaurantRecipe(Base):
    """
    Recipe header for a menu item, variant, or batch prep (Bill of Materials - BOM).
    Consolidated with embedded JSON line items.
    """
    __tablename__ = "restaurant_recipes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=True, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_menu_items.id", ondelete="CASCADE"), nullable=True, index=True)
    modifier_option_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    produced_ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="SET NULL"), nullable=True, index=True) # Semi-finished prep / sub-recipes
    variant_name = Column(String(50), default="Standard", nullable=False)
    yield_servings = Column(Numeric(6, 2), default=1.00, nullable=False)
    instructions = Column(Text, nullable=True)
    items = Column(JSON, default=list, nullable=False) # List of {ingredient_id, quantity_required, unit}

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet")
    item = relationship("RestaurantMenuItem")
    produced_ingredient = relationship("RestaurantIngredient", foreign_keys=[produced_ingredient_id])

    @property
    def lines(self):
        """Dynamic lines wrapper for backward compatibility."""
        if not self.items:
            return []
        res = []
        for it in self.items:
            ing_id = it.get("ingredient_id")
            if isinstance(ing_id, str):
                try:
                    ing_id = uuid.UUID(ing_id)
                except ValueError:
                    pass
            res.append(RecipeLineCompat(
                ingredient_id=ing_id,
                quantity_required=it.get("quantity_required", it.get("quantity", 1)),
                unit=it.get("unit", it.get("uom", "g"))
            ))
        return res

