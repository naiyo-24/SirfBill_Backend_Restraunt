import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Numeric, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantStockTransfer(Base):
    """
    Stock Transfer between branches (Commissary -> Outlet) or internal kitchen stations (Central Store -> Tandoor).
    Lifecycle: DRAFT -> IN_TRANSIT -> COMPLETED (or CANCELLED).
    Enforces multi-tenant isolation with composite unique key on (tenant_id, transfer_number).
    """
    __tablename__ = "restaurant_stock_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    transfer_number = Column(String(50), nullable=False) # e.g. ST-202611-0001
    
    # INTER_BRANCH (between different outlets) or INTER_STATION (within same outlet)
    transfer_type = Column(String(30), default="INTER_BRANCH", nullable=False)

    from_outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    to_outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)

    from_station = Column(String(100), nullable=True) # e.g. "Central Cold Store", "Dry Pantry"
    to_station = Column(String(100), nullable=True) # e.g. "Kitchen Line Chiller", "Tandoor Station", "Bar Counter"

    # Status: DRAFT, IN_TRANSIT, COMPLETED, CANCELLED
    status = Column(String(30), default="DRAFT", nullable=False, index=True)

    initiated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dispatched_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    dispatched_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)

    # Logistics tracking
    vehicle_number = Column(String(50), nullable=True)
    driver_name = Column(String(100), nullable=True)
    driver_phone = Column(String(50), nullable=True)

    total_items = Column(Integer, default=0, nullable=False)
    total_valuation = Column(Numeric(12, 2), default=0.00, nullable=False) # Total financial value in INR
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_stock_transfers_tenant_number", "tenant_id", "transfer_number", unique=True),
        Index("idx_stock_transfers_status", "tenant_id", "status"),
        Index("idx_stock_transfers_dates", "created_at"),
    )

    from_outlet = relationship("RestaurantOutlet", foreign_keys=[from_outlet_id])
    to_outlet = relationship("RestaurantOutlet", foreign_keys=[to_outlet_id])
    initiated_by = relationship("User", foreign_keys=[initiated_by_id])
    dispatched_by = relationship("User", foreign_keys=[dispatched_by_id])
    received_by = relationship("User", foreign_keys=[received_by_id])
    items = relationship("RestaurantStockTransferItem", back_populates="transfer", cascade="all, delete-orphan")


class RestaurantStockTransferItem(Base):
    """
    Line items within a stock transfer.
    Tracks requested, dispatched, and received quantities (Dual-UOM recipe units)
    and transit variances with financial valuation.
    """
    __tablename__ = "restaurant_stock_transfer_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Source branch ingredient
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    # Destination branch ingredient (mapped across branches or auto-cloned)
    destination_ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="SET NULL"), nullable=True, index=True)

    ingredient_name = Column(String(150), nullable=False)
    sku = Column(String(50), nullable=True)
    unit = Column(String(20), nullable=False) # Cooking recipe UOM (G, ML, PCS)

    quantity_requested = Column(Numeric(12, 3), default=0.000, nullable=False)
    quantity_dispatched = Column(Numeric(12, 3), default=0.000, nullable=False)
    quantity_received = Column(Numeric(12, 3), default=0.000, nullable=False)
    
    # quantity_variance = quantity_dispatched - quantity_received (> 0 means transit loss / shrinkage)
    quantity_variance = Column(Numeric(12, 3), default=0.000, nullable=False)
    
    unit_cost = Column(Numeric(12, 4), default=0.0000, nullable=False) # Snapshot unit cost at time of dispatch
    total_cost = Column(Numeric(12, 2), default=0.00, nullable=False) # quantity_dispatched * unit_cost

    variance_reason = Column(String(255), nullable=True) # e.g. "Transit Spillage", "Temperature Abuse", "Damaged in transit"
    batch_number = Column(String(100), nullable=True)
    expiry_date = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    transfer = relationship("RestaurantStockTransfer", back_populates="items")
    source_ingredient = relationship("RestaurantIngredient", foreign_keys=[ingredient_id])
    destination_ingredient = relationship("RestaurantIngredient", foreign_keys=[destination_ingredient_id])
