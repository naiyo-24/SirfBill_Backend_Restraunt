import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Numeric, Integer, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base
from utils.timezone import get_current_time

class SubscriptionPlan(Base):
    """
    Catalog of available subscription plans.
    Currently registered with the default ₹299/month restaurant plan.
    """
    __tablename__ = "subscription_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    plan_code = Column(String(50), unique=True, nullable=False, index=True) # e.g. "RESTAURANT_PRO_299"
    name = Column(String(100), nullable=False) # e.g. "SirfBill Restaurant Pro"
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), default=299.00, nullable=False) # 299.00 INR
    currency = Column(String(10), default="INR", nullable=False)
    billing_cycle = Column(String(20), default="MONTHLY", nullable=False) # MONTHLY, ANNUAL
    duration_days = Column(Integer, default=30, nullable=False)

    # Feature entitlements list
    features = Column(JSON, default=list, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    is_popular = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, nullable=False)

    subscriptions = relationship("TenantSubscription", back_populates="plan")


class TenantSubscription(Base):
    """
    Active / Historical subscription for a restaurant tenant.
    Purchased by the Super Admin / Tenant Owner.
    """
    __tablename__ = "tenant_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    outlet_id = Column(UUID(as_uuid=True), ForeignKey("restaurant_outlets.id", ondelete="SET NULL"), nullable=True, index=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True)

    status = Column(String(30), default="ACTIVE", nullable=False, index=True) # ACTIVE, TRIAL, EXPIRED, CANCELLED
    price_paid = Column(Numeric(10, 2), default=299.00, nullable=False)
    currency = Column(String(10), default="INR", nullable=False)

    started_at = Column(DateTime, default=get_current_time, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

    # Billing & Payment details
    payment_method = Column(String(50), default="UPI", nullable=True) # UPI, RAZORPAY, CARD, MANUAL, CASH
    payment_reference = Column(String(100), nullable=True) # Gateway Txn ID / UTR / Order ID
    invoice_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    auto_renew = Column(Boolean, default=True, nullable=False)
    purchased_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, nullable=False)

    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    outlet = relationship("RestaurantOutlet")
    purchased_by = relationship("User")
    payments = relationship("SubscriptionPayment", back_populates="subscription", cascade="all, delete-orphan")


class SubscriptionPayment(Base):
    """
    Audit log of all payment transactions for subscriptions.
    """
    __tablename__ = "subscription_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("tenant_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), default="INR", nullable=False)

    payment_gateway = Column(String(50), default="MANUAL_UPI", nullable=False) # RAZORPAY, PHONEPE, MANUAL_UPI, CASH
    gateway_order_id = Column(String(100), nullable=True)
    gateway_payment_id = Column(String(100), nullable=True)
    status = Column(String(30), default="SUCCESS", nullable=False) # SUCCESS, PENDING, FAILED

    payment_date = Column(DateTime, default=get_current_time, nullable=False)
    notes = Column(Text, nullable=True)

    subscription = relationship("TenantSubscription", back_populates="payments")
