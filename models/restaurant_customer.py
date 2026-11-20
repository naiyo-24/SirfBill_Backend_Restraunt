import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, Boolean, ForeignKey, Integer, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base

class RestaurantCustomer(Base):
    """
    Unified guest master: Tracks profile, dietary preferences, RFM metrics,
    loyalty points, and Khata (store credit) balance across all branches.
    """
    __tablename__ = "restaurant_customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    home_outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="SET NULL"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=False, index=True)
    email = Column(String(120), nullable=True)
    
    # Special dates for automated birthday/anniversary campaigns
    dob = Column(Date, nullable=True)
    anniversary = Column(Date, nullable=True)
    gst_number = Column(String(20), nullable=True) # Corporate client GSTIN

    # Dietary & preferences (e.g. {"dietary": "VEG", "spice": "MILD", "allergies": ["PEANUTS"]})
    preferences = Column(JSON, default=dict)
    # Dynamic RFM segments: ["NEW", "REGULAR", "VIP", "AT_RISK"]
    tags = Column(JSON, default=lambda: ["NEW"])

    # Cached RFM metrics (auto-updated on bill settlement)
    total_visits = Column(Integer, default=0, nullable=False)
    total_spent = Column(Numeric(12, 2), default=0.00, nullable=False)
    avg_order_value = Column(Numeric(10, 2), default=0.00, nullable=False)
    last_visit_at = Column(DateTime, nullable=True)

    # Loyalty & Credit Balance (Store Khata)
    loyalty_points = Column(Integer, default=0, nullable=False)
    credit_balance = Column(Numeric(12, 2), default=0.00, nullable=False) # Current unpaid Khata balance
    credit_limit = Column(Numeric(12, 2), default=0.00, nullable=False)   # Max allowed Khata exposure

    # Marketing consent
    opt_in_marketing = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    outlet = relationship("RestaurantOutlet", foreign_keys=[outlet_id])
    home_outlet = relationship("RestaurantOutlet", foreign_keys=[home_outlet_id])
    loyalty_ledger = relationship("RestaurantLoyaltyLedger", back_populates="customer", cascade="all, delete-orphan")
    credit_ledger = relationship("RestaurantCustomerCreditLedger", back_populates="customer", cascade="all, delete-orphan")
    notifications = relationship("RestaurantCrmNotification", back_populates="customer", cascade="all, delete-orphan")


class RestaurantLoyaltyRules(Base):
    """
    Brand-wide (tenant_id) loyalty rules configuration:
    Controls earn rates, redemption value, min order threshold, and point expiry.
    """
    __tablename__ = "restaurant_loyalty_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=True)

    earn_per_rupees = Column(Numeric(10, 2), default=100.00, nullable=False) # ₹ spend to earn 1 point
    point_value_inr = Column(Numeric(10, 2), default=1.00, nullable=False)   # INR value per redeemed point
    min_order_for_redeem = Column(Numeric(10, 2), default=200.00, nullable=False) # Min bill value to burn points
    max_redeem_pct = Column(Numeric(5, 2), default=20.00, nullable=False)    # Max % of bill payable via points
    points_expiry_days = Column(Integer, default=180, nullable=False)        # Expiration period in days
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RestaurantLoyaltyLedger(Base):
    """
    Append-only loyalty ledger: Points earned, redeemed, or reversed.
    Guarantees immutable accounting auditability.
    """
    __tablename__ = "restaurant_loyalty_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_customers.id", ondelete="CASCADE"), nullable=False, index=True)
    points_delta = Column(Integer, nullable=False) # Positive for earn, Negative for redeem
    balance_after = Column(Integer, default=0, nullable=False)
    reason = Column(String(50), nullable=False)    # ORDER_EARN, ORDER_REDEEM, MANUAL_ADJUSTMENT, REVERSAL, EXPIRED
    source_order_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_orders.id", ondelete="SET NULL"), nullable=True)

    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("RestaurantCustomer", back_populates="loyalty_ledger")
    order = relationship("RestaurantOrder")


class RestaurantCustomerCreditLedger(Base):
    """
    Append-only Khata ledger:
    - DEBIT: Store credit sale (adds to outstanding dues)
    - CREDIT: Customer settles partial or full dues
    """
    __tablename__ = "restaurant_customer_credit_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_customers.id", ondelete="CASCADE"), nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_orders.id", ondelete="SET NULL"), nullable=True)

    transaction_type = Column(String(20), nullable=False) # "DEBIT" (Dined on credit) or "CREDIT" (Paid dues)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    payment_mode = Column(String(50), nullable=True)      # "CASH", "UPI", "CARD", "BANK_TRANSFER"
    notes = Column(Text, nullable=True)
    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("RestaurantCustomer", back_populates="credit_ledger")
    order = relationship("RestaurantOrder")
    outlet = relationship("RestaurantOutlet")


class RestaurantCrmNotification(Base):
    """
    Multi-channel notification audit log:
    Tracks digital bill receipts, loyalty OTPs, Khata balance updates,
    birthday/anniversary offers, and inactive win-back alerts across WhatsApp, SMS & Email.
    """
    __tablename__ = "restaurant_crm_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_customers.id", ondelete="CASCADE"), nullable=True, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    channel = Column(String(20), nullable=False)   # WHATSAPP, SMS, EMAIL
    event_type = Column(String(40), nullable=False) # BILL_RECEIPT, LOYALTY_OTP, KHATA_ALERT, BIRTHDAY_OFFER, WINBACK, CUSTOM
    recipient = Column(String(120), nullable=False) # Phone number or email
    message_body = Column(Text, nullable=False)
    status = Column(String(20), default="SENT", nullable=False) # QUEUED, SENT, FAILED
    provider_ref = Column(String(100), nullable=True) # Gateway transaction ID (e.g. WhatsApp / MSG91 / SendGrid)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("RestaurantCustomer", back_populates="notifications")
    outlet = relationship("RestaurantOutlet")
