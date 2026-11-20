from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field

# ----------------- Customer Profile Schemas -----------------
class RestaurantCustomerBase(BaseModel):
    name: str = Field(..., max_length=150)
    phone: str = Field(..., max_length=20)
    email: Optional[str] = None
    dob: Optional[date] = None
    anniversary: Optional[date] = None
    gst_number: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    credit_limit: Optional[Decimal] = Decimal("0.00")
    opt_in_marketing: bool = True
    notes: Optional[str] = None
    is_active: bool = True

class RestaurantCustomerCreate(RestaurantCustomerBase):
    outlet_id: UUID

class RestaurantCustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    dob: Optional[date] = None
    anniversary: Optional[date] = None
    gst_number: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    credit_limit: Optional[Decimal] = None
    opt_in_marketing: Optional[bool] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

class RestaurantCustomerResponse(RestaurantCustomerBase):
    id: UUID
    outlet_id: UUID
    home_outlet_id: Optional[UUID] = None
    tenant_id: UUID
    total_visits: int
    total_spent: Decimal
    avg_order_value: Decimal
    last_visit_at: Optional[datetime] = None
    loyalty_points: int
    credit_balance: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- Customer Insights Schemas -----------------
class CustomerTopDish(BaseModel):
    item_name: str
    variant_name: Optional[str] = None
    order_count: int
    total_spent: Decimal

class CustomerRecentBill(BaseModel):
    order_id: UUID
    order_number: str
    order_type: str
    grand_total: Decimal
    created_at: datetime

class CustomerInsightsResponse(BaseModel):
    customer_id: UUID
    name: str
    phone: str
    total_visits: int
    total_spent: Decimal
    avg_order_value: Decimal
    loyalty_points: int
    credit_balance: Decimal
    credit_limit: Decimal
    current_segment: str # VIP, REGULAR, NEW, AT_RISK
    last_visit_at: Optional[datetime] = None
    top_dishes: List[CustomerTopDish]
    recent_bills: List[CustomerRecentBill]


# ----------------- Loyalty Rules & Ledger Schemas -----------------
class LoyaltyRulesBase(BaseModel):
    earn_per_rupees: Decimal = Field(Decimal("100.00"), description="Spend to earn 1 pt")
    point_value_inr: Decimal = Field(Decimal("1.00"), description="Value of 1 pt in INR")
    min_order_for_redeem: Decimal = Field(Decimal("200.00"), description="Min bill to burn points")
    max_redeem_pct: Decimal = Field(Decimal("20.00"), description="Max bill % payable via points")
    points_expiry_days: int = Field(180, description="Points validity in days")
    is_active: bool = True

class LoyaltyRulesResponse(LoyaltyRulesBase):
    id: UUID
    tenant_id: UUID
    outlet_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LoyaltyPointsAdjustment(BaseModel):
    points_delta: int
    reason: str
    source_order_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

class LoyaltyLedgerResponse(BaseModel):
    id: UUID
    customer_id: UUID
    points_delta: int
    balance_after: int
    reason: str
    source_order_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- Khata / Store Credit Schemas -----------------
class KhataSettleRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    payment_mode: str = "CASH" # CASH, UPI, CARD, BANK_TRANSFER
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None

class KhataLedgerResponse(BaseModel):
    id: UUID
    customer_id: UUID
    outlet_id: UUID
    order_id: Optional[UUID] = None
    transaction_type: str # DEBIT or CREDIT
    amount: Decimal
    balance_after: Decimal
    payment_mode: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class KhataStatementResponse(BaseModel):
    customer_id: UUID
    customer_name: str
    phone: str
    credit_balance: Decimal
    credit_limit: Decimal
    ledger: List[KhataLedgerResponse]


# ----------------- Notifications & Automations Schemas -----------------
class CrmNotificationSendRequest(BaseModel):
    channel: str = "WHATSAPP" # WHATSAPP, SMS, EMAIL
    event_type: str = "CUSTOM"
    message_body: str
    recipient: Optional[str] = None

class CrmNotificationResponse(BaseModel):
    id: UUID
    customer_id: Optional[UUID] = None
    outlet_id: UUID
    channel: str
    event_type: str
    recipient: str
    message_body: str
    status: str
    provider_ref: Optional[str] = None
    created_at: datetime
    sent_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AutomationsRunResponse(BaseModel):
    status: str
    birthdays_triggered: int
    anniversaries_triggered: int
    winback_triggered: int
    message: str
