from pydantic import BaseModel, ConfigDict, field_serializer
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal

class SubscriptionPlanResponse(BaseModel):
    id: UUID
    plan_code: str
    name: str
    description: Optional[str] = None
    price: Decimal # Base price from database (GST excluded)
    base_price: Optional[Decimal] = None # Explicit Base price
    gst_rate: float = 18.0 # Standard 18% GST rate
    gst_amount: Optional[Decimal] = None # Calculated 18% GST
    total_price: Optional[Decimal] = None # Base + 18% GST
    currency: str = "INR"
    billing_cycle: str
    duration_days: int
    gst_note: str = "GST (18%) Excluded"
    price_display: Optional[str] = None # e.g. "₹299 (GST Excluded)"
    total_display: Optional[str] = None # e.g. "₹353 (Incl. 18% GST)"
    features: List[str] = []
    is_active: bool
    is_popular: bool
    created_at: datetime

    @field_serializer("price", check_fields=False)
    def serialize_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("base_price", check_fields=False)
    def serialize_base_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("gst_amount", check_fields=False)
    def serialize_gst_amount(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("total_price", check_fields=False)
    def serialize_total_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)


class SubscriptionPlanCreate(BaseModel):
    plan_code: str
    name: str
    description: Optional[str] = None
    price: Decimal
    currency: Optional[str] = "INR"
    billing_cycle: Optional[str] = "MONTHLY"
    duration_days: Optional[int] = 30
    features: Optional[List[str]] = []
    is_active: Optional[bool] = True
    is_popular: Optional[bool] = False


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    currency: Optional[str] = None
    billing_cycle: Optional[str] = None
    duration_days: Optional[int] = None
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_popular: Optional[bool] = None


class SubscribeRequest(BaseModel):
    plan_id: Optional[UUID] = None # Optional if subscribing to the default 299 plan
    plan_code: Optional[str] = None # e.g. RESTAURANT_PRO_3M, RESTAURANT_PRO_6M, RESTAURANT_PRO_12M
    duration_months: Optional[int] = None # 1, 3, 6, 12
    outlet_id: Optional[UUID] = None # Target outlet or primary tenant
    payment_method: Optional[str] = "UPI" # UPI, RAZORPAY, CARD, MANUAL, CASH
    payment_reference: Optional[str] = None # UTR / Transaction ID
    notes: Optional[str] = None


class RazorpayOrderCreate(BaseModel):
    plan_id: Optional[UUID] = None
    plan_code: Optional[str] = None
    duration_months: Optional[int] = None
    outlet_id: Optional[UUID] = None
    callback_url: Optional[str] = None


class RazorpayOrderResponse(BaseModel):
    order_id: Optional[str] = None
    amount: Decimal # Total payable (including 18% GST)
    amount_paise: int
    base_price: Optional[Decimal] = None # Base price (GST excluded)
    gst_amount: Optional[Decimal] = None # 18% GST
    currency: str
    key_id: str
    plan_id: UUID
    plan_name: str
    plan_code: Optional[str] = None
    duration_days: Optional[int] = None
    billing_cycle: Optional[str] = None
    outlet_id: Optional[UUID] = None
    payment_link_url: Optional[str] = None

    @field_serializer("amount", check_fields=False)
    def serialize_amount(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("base_price", check_fields=False)
    def serialize_base_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("gst_amount", check_fields=False)
    def serialize_gst_amount(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: str
    razorpay_signature: Optional[str] = None
    plan_id: Optional[UUID] = None
    plan_code: Optional[str] = None
    duration_months: Optional[int] = None
    outlet_id: Optional[UUID] = None
    notes: Optional[str] = None


class TenantSubscriptionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    outlet_id: Optional[UUID] = None
    plan_id: UUID
    plan_name: Optional[str] = None
    plan_code: Optional[str] = None
    status: str # ACTIVE, TRIAL, EXPIRED, CANCELLED
    price_paid: Decimal
    currency: str
    started_at: datetime
    expires_at: datetime
    days_remaining: int
    is_active: bool
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_url: Optional[str] = None
    download_url: Optional[str] = None
    features: List[str] = []
    created_at: datetime

    @field_serializer("price_paid", check_fields=False)
    def serialize_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)


class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    is_active: bool
    status: str # ACTIVE, TRIAL, EXPIRED, NONE
    plan_name: Optional[str] = None
    price: Optional[Decimal] = None # Base price
    base_price: Optional[Decimal] = None
    gst_note: str = "GST (18%) Excluded"
    total_price: Optional[Decimal] = None
    billing_cycle: Optional[str] = None
    expires_at: Optional[datetime] = None
    days_remaining: int
    features: List[str] = []
    outlet_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    latest_invoice_number: Optional[str] = None
    latest_invoice_url: Optional[str] = None
    latest_download_url: Optional[str] = None

    @field_serializer("price", check_fields=False)
    def serialize_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("base_price", check_fields=False)
    def serialize_base_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("total_price", check_fields=False)
    def serialize_total_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)


class SubscriptionInvoiceResponse(BaseModel):
    id: UUID
    invoice_number: str
    tenant_id: UUID
    outlet_id: Optional[UUID] = None
    outlet_name: Optional[str] = None
    plan_name: str
    subtotal: float
    tax_amount: float
    cgst: float
    sgst: float
    total_amount: float
    currency: str = "INR"
    payment_method: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_status: str = "SUCCESS"
    issue_date: datetime
    formatted_issue_date: str
    expires_at: Optional[datetime] = None
    formatted_expires_at: Optional[str] = None
    view_url: str
    download_url: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class SubscriptionPaymentResponse(BaseModel):
    id: UUID
    subscription_id: UUID
    tenant_id: UUID
    amount: Decimal
    currency: str
    payment_gateway: str
    gateway_order_id: Optional[str] = None
    gateway_payment_id: Optional[str] = None
    status: str
    payment_date: datetime
    notes: Optional[str] = None

    @field_serializer("amount", check_fields=False)
    def serialize_amount(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)


class BranchSubscriptionResponse(BaseModel):
    outlet_id: UUID
    outlet_name: str
    outlet_code: Optional[str] = None
    city: Optional[str] = None
    is_primary: bool = False
    has_subscription: bool = False
    is_active: bool = False
    status: str = "UNPAID" # ACTIVE, TRIAL, EXPIRED, PENDING_PAYMENT, UNPAID
    plan_name: Optional[str] = None
    plan_code: Optional[str] = None
    price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    billing_cycle: Optional[str] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    days_remaining: int = 0
    latest_invoice_number: Optional[str] = None
    latest_invoice_url: Optional[str] = None
    latest_download_url: Optional[str] = None

    @field_serializer("price", check_fields=False)
    def serialize_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    @field_serializer("total_price", check_fields=False)
    def serialize_total_price(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)

