from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field

# ----------------- SUPPLIERS -----------------

class RestaurantSupplierBase(BaseModel):
    name: str = Field(..., max_length=150)
    code: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=120)
    address: Optional[str] = None
    gstin: Optional[str] = Field(None, max_length=50)
    fssai: Optional[str] = Field(None, max_length=50)
    payment_terms: Optional[str] = "NET_15"
    bank_details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    is_active: bool = True

class RestaurantSupplierCreate(RestaurantSupplierBase):
    outlet_id: Optional[UUID] = None

class RestaurantSupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    code: Optional[str] = Field(None, max_length=50)
    contact_person: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=120)
    address: Optional[str] = None
    gstin: Optional[str] = Field(None, max_length=50)
    fssai: Optional[str] = Field(None, max_length=50)
    payment_terms: Optional[str] = None
    bank_details: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

class RestaurantSupplierResponse(RestaurantSupplierBase):
    id: UUID
    outlet_id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- PURCHASE ORDER ITEMS -----------------

class PurchaseOrderItemInput(BaseModel):
    ingredient_id: UUID
    quantity_ordered: Decimal = Field(..., gt=0)
    unit: str = "KG"
    unit_price: Decimal = Field(Decimal("0.00"), ge=0)
    tax_rate: Decimal = Field(Decimal("0.00"), ge=0)
    notes: Optional[str] = None

class PurchaseOrderItemResponse(BaseModel):
    id: UUID
    po_id: UUID
    ingredient_id: UUID
    ingredient_name: Optional[str] = None
    ingredient_sku: Optional[str] = None
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit: str
    unit_price: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total_price: Decimal
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ----------------- PURCHASE ORDERS -----------------

class PurchaseOrderCreate(BaseModel):
    outlet_id: Optional[UUID] = None
    supplier_id: UUID
    order_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: List[PurchaseOrderItemInput] = []

class PurchaseOrderUpdate(BaseModel):
    supplier_id: Optional[UUID] = None
    order_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[PurchaseOrderItemInput]] = None

class PurchaseOrderEmailRequest(BaseModel):
    email: Optional[str] = None
    message: Optional[str] = None

class PurchaseOrderResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    outlet_name: Optional[str] = None
    outlet_address: Optional[str] = None
    outlet_city: Optional[str] = None
    outlet_phone: Optional[str] = None
    outlet_email: Optional[str] = None
    outlet_gstin: Optional[str] = None
    tenant_id: UUID
    supplier_id: UUID
    supplier_name: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_email: Optional[str] = None
    supplier_address: Optional[str] = None
    po_number: str
    status: str
    status_label: Optional[str] = None # e.g. "Sent to Vendor", "Partial Delivery"
    order_date: date
    expected_delivery_date: Optional[date] = None
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    created_by_name: Optional[str] = None
    fulfillment_percentage: Decimal = Decimal("0.00")
    items: List[PurchaseOrderItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PurchaseOrderSummaryResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    outlet_name: Optional[str] = None
    outlet_address: Optional[str] = None
    outlet_city: Optional[str] = None
    outlet_phone: Optional[str] = None
    outlet_email: Optional[str] = None
    outlet_gstin: Optional[str] = None
    supplier_id: UUID
    supplier_name: Optional[str] = None
    supplier_phone: Optional[str] = None
    supplier_email: Optional[str] = None
    po_number: str
    status: str
    status_label: Optional[str] = None # e.g. "Sent to Vendor", "Partial Delivery"
    order_date: date
    expected_delivery_date: Optional[date] = None
    subtotal: Decimal = Decimal("0.00")
    total_amount: Decimal
    items_count: int = 0
    fulfillment_percentage: Decimal = Decimal("0.00")
    items: List[PurchaseOrderItemResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- GOODS RECEIVED NOTE (GRN) -----------------

class GRNItemInput(BaseModel):
    ingredient_id: UUID
    po_item_id: Optional[UUID] = None
    quantity_received: Decimal = Field(Decimal("0.000"), ge=0, description="Net acceptable quantity entering stock")
    quantity_rejected: Decimal = Field(Decimal("0.000"), ge=0, description="Damaged/spoiled goods rejected at dock")
    rejection_reason: Optional[str] = None
    unit: str = "KG"
    unit_price: Decimal = Field(Decimal("0.00"), ge=0)
    actual_unit_price: Optional[Decimal] = Field(None, ge=0, description="Actual physical vendor invoice price for WAC recalculation")
    tax_rate: Decimal = Field(Decimal("0.00"), ge=0)
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None

class GRNItemResponse(BaseModel):
    id: UUID
    grn_id: UUID
    ingredient_id: UUID
    ingredient_name: Optional[str] = None
    po_item_id: Optional[UUID] = None
    quantity_received: Decimal
    quantity_rejected: Decimal = Decimal("0.000")
    rejection_reason: Optional[str] = None
    unit: str
    unit_price: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total_price: Decimal
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)

class GRNCreate(BaseModel):
    outlet_id: Optional[UUID] = None
    po_id: Optional[UUID] = None
    supplier_id: UUID
    supplier_invoice_no: Optional[str] = None
    invoice_date: Optional[date] = None
    invoice_document_url: Optional[str] = None
    payment_status: Optional[str] = "UNPAID" # UNPAID, PARTIAL, PAID
    remarks: Optional[str] = None
    items: List[GRNItemInput] = []

class GRNResponse(BaseModel):
    id: UUID
    outlet_id: UUID
    tenant_id: UUID
    po_id: Optional[UUID] = None
    po_number: Optional[str] = None
    supplier_id: UUID
    supplier_name: Optional[str] = None
    grn_number: str
    supplier_invoice_no: Optional[str] = None
    invoice_date: Optional[date] = None
    invoice_document_url: Optional[str] = None
    received_date: datetime
    total_amount: Decimal
    payment_status: str
    remarks: Optional[str] = None
    items: List[GRNItemResponse] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
