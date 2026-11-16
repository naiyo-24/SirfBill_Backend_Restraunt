import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Numeric, Text, Date, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantSupplier(Base):
    """
    Supplier / Vendor Master: e.g. Poultry Farm, Dairy Co-op, Spices Trader, Produce Market.
    Isolated by outlet_id (or tenant-wide if outlet_id is NULL) and tenant_id.
    """
    __tablename__ = "restaurant_suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(150), nullable=False, index=True)
    code = Column(String(50), nullable=True, index=True) # e.g. SUP-DAIRY-01
    contact_person = Column(String(100), nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(120), nullable=True)
    address = Column(Text, nullable=True)
    gstin = Column(String(50), nullable=True)
    fssai = Column(String(50), nullable=True)
    payment_terms = Column(String(50), default="NET_15", nullable=True) # NET_7, NET_15, NET_30, COD, ADVANCE
    bank_details = Column(JSON, default=dict) # {"bank_name": "", "account_no": "", "ifsc": "", "upi_id": ""}
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet")
    purchase_orders = relationship("RestaurantPurchaseOrder", back_populates="supplier")
    grns = relationship("RestaurantGRN", back_populates="supplier")


class RestaurantPurchaseOrder(Base):
    """
    Purchase Order (PO) Header: Group raw ingredient orders sent to a supplier.
    Lifecycle: DRAFT -> ISSUED -> PARTIALLY_RECEIVED -> COMPLETED (or CANCELLED)
    """
    __tablename__ = "restaurant_purchase_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)

    po_number = Column(String(50), nullable=False, index=True) # e.g. PO-202611-001
    status = Column(String(30), default="DRAFT", nullable=False, index=True) # DRAFT, ISSUED, PARTIALLY_RECEIVED, COMPLETED, CANCELLED

    order_date = Column(Date, default=datetime.utcnow().date, nullable=False)
    expected_delivery_date = Column(Date, nullable=True)

    subtotal = Column(Numeric(12, 2), default=0.00, nullable=False)
    tax_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_amount = Column(Numeric(12, 2), default=0.00, nullable=False)

    delivery_address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet")
    supplier = relationship("RestaurantSupplier", back_populates="purchase_orders")
    created_by = relationship("User", foreign_keys=[created_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    items = relationship("RestaurantPurchaseOrderItem", back_populates="po", cascade="all, delete-orphan")
    grns = relationship("RestaurantGRN", back_populates="po")


class RestaurantPurchaseOrderItem(Base):
    """
    Purchase Order Line Items: Specific ingredient, quantity ordered, unit price.
    Tracks quantity_received to determine partial vs full receipt.
    """
    __tablename__ = "restaurant_purchase_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="RESTRICT"), nullable=False, index=True)

    quantity_ordered = Column(Numeric(12, 3), nullable=False)
    quantity_received = Column(Numeric(12, 3), default=0.000, nullable=False)
    unit = Column(String(20), nullable=False) # KG, G, L, ML, PCS
    unit_price = Column(Numeric(10, 2), default=0.00, nullable=False)
    tax_rate = Column(Numeric(5, 2), default=0.00, nullable=False)
    tax_amount = Column(Numeric(10, 2), default=0.00, nullable=False)
    total_price = Column(Numeric(12, 2), default=0.00, nullable=False)
    notes = Column(String(255), nullable=True)

    po = relationship("RestaurantPurchaseOrder", back_populates="items")
    ingredient = relationship("RestaurantIngredient")


class RestaurantGRN(Base):
    """
    Goods Received Note (GRN): Generated when stock physically arrives at kitchen dock.
    """
    __tablename__ = "restaurant_grn"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    po_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)

    grn_number = Column(String(50), nullable=False, index=True) # e.g. GRN-202611-001
    supplier_invoice_no = Column(String(100), nullable=True)
    invoice_date = Column(Date, nullable=True)
    invoice_document_url = Column(String(500), nullable=True) # Digital bill scan / PDF
    received_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    received_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    total_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    payment_status = Column(String(30), default="UNPAID", nullable=False) # UNPAID, PARTIAL, PAID
    remarks = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet")
    supplier = relationship("RestaurantSupplier", back_populates="grns")
    po = relationship("RestaurantPurchaseOrder", back_populates="grns")
    received_by = relationship("User")
    items = relationship("RestaurantGRNItem", back_populates="grn", cascade="all, delete-orphan")


class RestaurantGRNItem(Base):
    """
    Goods Received Note Line Item: Received quantity that directly debits into stock ledger.
    Tracks quantity_rejected for damaged/spoiled items and batch/expiry for kitchen FIFO/FEFO.
    """
    __tablename__ = "restaurant_grn_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grn_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_grn.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_ingredients.id", ondelete="RESTRICT"), nullable=False, index=True)
    po_item_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_purchase_order_items.id", ondelete="SET NULL"), nullable=True)

    quantity_received = Column(Numeric(12, 3), nullable=False) # Net acceptable quantity entering stock
    quantity_rejected = Column(Numeric(12, 3), default=0.000, nullable=False) # Spoiled / damaged / expired goods
    rejection_reason = Column(String(255), nullable=True) # e.g. "Damaged packaging", "Spoiled / temp breach"
    unit = Column(String(20), nullable=False)
    unit_price = Column(Numeric(10, 2), default=0.00, nullable=False) # Actual price from vendor delivery bill
    tax_rate = Column(Numeric(5, 2), default=0.00, nullable=False)
    tax_amount = Column(Numeric(10, 2), default=0.00, nullable=False)
    total_price = Column(Numeric(12, 2), default=0.00, nullable=False)
    batch_number = Column(String(50), nullable=True)
    expiry_date = Column(Date, nullable=True)

    grn = relationship("RestaurantGRN", back_populates="items")
    ingredient = relationship("RestaurantIngredient")
    po_item = relationship("RestaurantPurchaseOrderItem")
