import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Date, ForeignKey, Numeric, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base
from utils.timezone import get_current_time, get_current_date

class RestaurantStockAudit(Base):
    """
    Physical Stock Audit Batch Header.
    Preserves audit sessions, including all counted items (surplus, deficit, and matched).
    """
    __tablename__ = "restaurant_stock_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_code = Column(String(100), unique=True, nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    auditor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    audit_date = Column(Date, default=get_current_date, nullable=False)
    audit_started_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    total_items_audited = Column(Integer, default=0, nullable=False)
    items_adjusted = Column(Integer, default=0, nullable=False)
    total_surplus_rupees = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_deficit_rupees = Column(Numeric(12, 2), default=0.00, nullable=False)
    net_variance_rupees = Column(Numeric(12, 2), default=0.00, nullable=False)

    created_at = Column(DateTime, default=get_current_time, nullable=False)

    outlet = relationship("RestaurantOutlet")
    auditor = relationship("User")
    items = relationship("RestaurantStockAuditItem", back_populates="audit", cascade="all, delete-orphan", order_by="RestaurantStockAuditItem.created_at")


class RestaurantStockAuditItem(Base):
    """
    Individual ingredient physical count record in an audit batch.
    Stores full audit proof, including MATCHED items with 0 variance.
    """
    __tablename__ = "restaurant_stock_audit_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_stock_audits.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="CASCADE"), nullable=False, index=True)

    ingredient_name = Column(String(150), nullable=True)
    recipe_uom = Column(String(20), nullable=False)
    purchase_uom = Column(String(20), nullable=True)
    input_uom = Column(String(20), default="RECIPE", nullable=True)

    previous_stock = Column(Numeric(12, 3), default=0.000, nullable=False)
    expected_stock = Column(Numeric(12, 3), nullable=True) # Stock at the moment count started (snapshot)
    physical_count = Column(Numeric(12, 3), default=0.000, nullable=False) # In recipe UOM
    raw_input_count = Column(Numeric(12, 3), nullable=True) # What auditor literally typed
    variance = Column(Numeric(12, 3), default=0.000, nullable=False) # physical_count - previous_stock
    unit_cost_at_time = Column(Numeric(12, 4), default=0.0000, nullable=False)
    variance_rupees = Column(Numeric(12, 2), default=0.00, nullable=False)
    status = Column(String(20), default="MATCHED", nullable=False) # "MATCHED", "SURPLUS", "DEFICIT"
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=get_current_time, nullable=False)

    audit = relationship("RestaurantStockAudit", back_populates="items")
    ingredient = relationship("RestaurantIngredient")
