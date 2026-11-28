import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Numeric, Integer, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base
from utils.timezone import get_current_time

class HardwareProduct(Base):
    """
    Catalog of restaurant hardware available for purchase:
    Thermal printers, POS terminals, KDS screens, barcode scanners,
    electronic cash drawers, handheld ordering tablets, and paper rolls.
    """
    __tablename__ = "hardware_products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    sku = Column(String(50), unique=True, nullable=False, index=True) # e.g. "SB-PRN-80MM-01"
    name = Column(String(200), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True) # PRINTER, POS_TERMINAL, SCANNER, CASH_DRAWER, KDS_DISPLAY, HANDHELD_PDA, ACCESSORY, PAPER_ROLLS
    brand = Column(String(100), default="SirfBill", nullable=False)
    model_number = Column(String(100), nullable=True)

    short_description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    # Key hardware specifications: {"connectivity": ["USB", "LAN", "Bluetooth"], "print_speed": "260 mm/s", ...}
    specifications = Column(JSON, default=dict, nullable=False)
    # Highlights / bullet points: ["Auto cutter (1.5M cuts)", "Triple interface", "1 Year Warranty"]
    features = Column(JSON, default=list, nullable=False)

    # Pricing & Taxes
    price = Column(Numeric(10, 2), nullable=False) # Current selling price in INR
    mrp = Column(Numeric(10, 2), nullable=True)     # Strike-through MRP in INR
    discount_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    tax_rate = Column(Numeric(5, 2), default=18.00, nullable=False) # 18% GST standard for IT hardware

    # Media & Inventory
    primary_image_url = Column(Text, nullable=True)
    images = Column(JSON, default=list, nullable=False) # Gallery image URLs
    stock_quantity = Column(Integer, default=50, nullable=False)
    in_stock = Column(Boolean, default=True, nullable=False)
    warranty_months = Column(Integer, default=12, nullable=False) # Standard 1-year brand warranty

    # Badges & Flags
    is_popular = Column(Boolean, default=False, nullable=False) # "Bestseller" badge
    is_featured = Column(Boolean, default=False, nullable=False) # Featured on home / header
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, nullable=False)

    orders = relationship("HardwareOrder", back_populates="product", cascade="all, delete-orphan")


class HardwareOrder(Base):
    """
    Hardware purchase inquiry / order placed by a restaurant tenant:
    Tracks quantity, pricing, customer delivery address, payment, and dispatch fulfillment status.
    """
    __tablename__ = "hardware_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("hardware_products.id", ondelete="RESTRICT"), nullable=True, index=True)

    order_number = Column(String(50), unique=True, nullable=False, index=True) # e.g. "HWO-202611-0001"
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), default=0.00, nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)

    # Optional Service Plan & Order Source (for combined hardware + subscription / WhatsApp orders)
    plan_id = Column(String(100), nullable=True)
    plan_name = Column(String(150), nullable=True)
    plan_price = Column(Numeric(10, 2), default=0.00, nullable=False)
    order_type = Column(String(30), default="HARDWARE", nullable=False) # HARDWARE, SERVICE_PLAN, COMBINED
    order_source = Column(String(30), default="DASHBOARD", nullable=False) # DASHBOARD, WHATSAPP

    # Delivery & Contact Information
    contact_name = Column(String(150), nullable=False)
    contact_phone = Column(String(30), nullable=False)
    contact_email = Column(String(120), nullable=True)
    shipping_address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(20), nullable=True)

    # Fulfillment & Payment Status
    status = Column(String(30), default="NEW", nullable=False, index=True) # NEW, CONFIRMED, INVOICED, SHIPPED, DELIVERED, CANCELLED
    payment_status = Column(String(30), default="PENDING", nullable=False) # PENDING, PAID, COD
    payment_method = Column(String(50), default="UPI", nullable=True)     # UPI, RAZORPAY, COD, BANK_TRANSFER
    payment_reference = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    courier_partner = Column(String(100), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, nullable=False)

    product = relationship("HardwareProduct", back_populates="orders")
    outlet = relationship("RestaurantOutlet")
