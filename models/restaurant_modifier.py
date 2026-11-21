import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantModifierGroup(Base):
    """
    Modifier Group: e.g. 'Spice Level', 'Choice of Crust', 'Add-on Toppings'
    Consolidated with embedded JSONB options and applicable item associations.
    """
    __tablename__ = "restaurant_modifier_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    min_selection = Column(Integer, default=0, nullable=False) # 0 means optional
    max_selection = Column(Integer, default=1, nullable=False) # 1 for single-choice, >1 for multi-choice
    is_active = Column(Boolean, default=True, nullable=False)

    options = Column(JSON, default=list, nullable=False) # Embedded list of {id, name, price_delta, is_available}
    applicable_item_ids = Column(JSON, default=list, nullable=False) # List of UUIDs of menu items

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

