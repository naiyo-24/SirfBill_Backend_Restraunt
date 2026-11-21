from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field

# ----------------- Hardware Catalog Schemas -----------------
class HardwareProductBase(BaseModel):
    sku: str = Field(..., max_length=50, description="Unique stock keeping unit code")
    name: str = Field(..., max_length=200, description="Product title")
    category: str = Field(..., max_length=50, description="PRINTER, POS_TERMINAL, SCANNER, CASH_DRAWER, KDS_DISPLAY, HANDHELD_PDA, ACCESSORY, PAPER_ROLLS")
    brand: str = Field("SirfBill", max_length=100)
    model_number: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    specifications: Optional[Dict[str, Any]] = Field(default_factory=dict)
    features: Optional[List[str]] = Field(default_factory=list)
    price: Decimal = Field(..., gt=0, description="Selling price in INR")
    mrp: Optional[Decimal] = Field(None, description="Original list price / MRP")
    discount_pct: Decimal = Field(Decimal("0.00"), ge=0, le=100)
    tax_rate: Decimal = Field(Decimal("18.00"), description="GST rate percentage")
    primary_image_url: Optional[str] = None
    images: Optional[List[str]] = Field(default_factory=list)
    stock_quantity: int = Field(50, ge=0)
    in_stock: bool = True
    warranty_months: int = Field(12, ge=0)
    is_popular: bool = False
    is_featured: bool = False
    is_active: bool = True
    sort_order: int = 0

class HardwareProductCreate(HardwareProductBase):
    pass

class HardwareProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    model_number: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    specifications: Optional[Dict[str, Any]] = None
    features: Optional[List[str]] = None
    price: Optional[Decimal] = None
    mrp: Optional[Decimal] = None
    discount_pct: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    primary_image_url: Optional[str] = None
    images: Optional[List[str]] = None
    stock_quantity: Optional[int] = None
    in_stock: Optional[bool] = None
    warranty_months: Optional[int] = None
    is_popular: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

class HardwareProductResponse(HardwareProductBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class HardwareCategorySummary(BaseModel):
    category: str
    title: str
    count: int
    icon: str
    description: str

# ----------------- Hardware Purchase & Inquiry Schemas -----------------
class HardwareOrderCreate(BaseModel):
    product_id: UUID
    outlet_id: Optional[UUID] = None
    quantity: int = Field(1, ge=1)
    contact_name: str = Field(..., max_length=150)
    contact_phone: str = Field(..., max_length=30)
    contact_email: Optional[str] = None
    shipping_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    payment_method: str = "UPI" # UPI, RAZORPAY, COD, BANK_TRANSFER
    notes: Optional[str] = None

class HardwareOrderUpdate(BaseModel):
    status: Optional[str] = None # NEW, CONFIRMED, INVOICED, SHIPPED, DELIVERED, CANCELLED
    payment_status: Optional[str] = None # PENDING, PAID, COD
    tracking_number: Optional[str] = None
    courier_partner: Optional[str] = None
    notes: Optional[str] = None

class HardwareOrderResponse(BaseModel):
    id: UUID
    order_number: str
    tenant_id: UUID
    outlet_id: Optional[UUID] = None
    product_id: UUID
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    contact_name: str
    contact_phone: str
    contact_email: Optional[str] = None
    shipping_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    tracking_number: Optional[str] = None
    courier_partner: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    product: Optional[HardwareProductResponse] = None

    model_config = ConfigDict(from_attributes=True)
