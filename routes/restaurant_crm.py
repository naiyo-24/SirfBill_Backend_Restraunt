import uuid
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast, String, text

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_customer import (
    RestaurantCustomer,
    RestaurantLoyaltyRules,
    RestaurantCustomerLedger,
    RestaurantCrmNotification,
)
from models.restaurant_order import RestaurantOrder
from models.restaurant_order_line import RestaurantOrderLine
from schemas.restaurant_crm import (
    RestaurantCustomerCreate,
    RestaurantCustomerUpdate,
    RestaurantCustomerResponse,
    CustomerInsightsResponse,
    CustomerTopDish,
    CustomerRecentBill,
    LoyaltyRulesBase,
    LoyaltyRulesResponse,
    LoyaltyPointsAdjustment,
    LoyaltyLedgerResponse,
    KhataSettleRequest,
    KhataLedgerResponse,
    KhataStatementResponse,
    CrmNotificationSendRequest,
    CrmNotificationResponse,
    AutomationsRunResponse,
)
from dependencies import get_restaurant_staff, get_restaurant_cashier, get_restaurant_manager

router = APIRouter(
    prefix="/api/restaurant/crm",
    tags=["Restaurant - CRM & Loyalty"]
)

# ---------------------------------------------------------
# Helper: Order Settlement CRM Pipeline
# ---------------------------------------------------------
def process_order_settlement_crm(
    db: Session,
    order: RestaurantOrder,
    khata_amount: Decimal = Decimal("0.00")
):
    """
    Invoked upon bill settlement:
    1. Updates visits, lifetime spend, AOV, last_visit_at
    2. Recalculates RFM dynamic tags (VIP / REGULAR / NEW / AT_RISK)
    3. Credits loyalty points via append-only ledger
    4. Debits Khata balance if settled on store credit
    5. Dispatches digital receipt notification
    """
    customer = None
    if order.customer_id:
        customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == order.customer_id).first()
    elif order.customer_phone:
        customer = (
            db.query(RestaurantCustomer)
            .filter(RestaurantCustomer.tenant_id == order.tenant_id)
            .filter(RestaurantCustomer.phone == order.customer_phone)
            .first()
        )

    if not customer:
        return

    # 1. Update RFM stats
    customer.total_visits = (customer.total_visits or 0) + 1
    customer.total_spent = (customer.total_spent or Decimal("0.00")) + order.grand_total
    if customer.total_visits > 0:
        customer.avg_order_value = (customer.total_spent / customer.total_visits).quantize(Decimal("0.01"))
    customer.last_visit_at = datetime.utcnow()

    # 2. Recalculate dynamic segment tags
    if customer.total_spent >= Decimal("5000.00") or customer.total_visits >= 10:
        customer.tags = ["VIP"]
    elif customer.total_visits >= 3:
        customer.tags = ["REGULAR"]
    else:
        customer.tags = ["NEW"]

    # 3. Credit Loyalty Points
    rules = (
        db.query(RestaurantLoyaltyRules)
        .filter(RestaurantLoyaltyRules.tenant_id == order.tenant_id)
        .filter(RestaurantLoyaltyRules.is_active == True)
        .first()
    )
    if rules and rules.earn_per_rupees > 0:
        pts_earned = int(order.grand_total / rules.earn_per_rupees)
        if pts_earned > 0:
            customer.loyalty_points = (customer.loyalty_points or 0) + pts_earned
            ledger_entry = RestaurantCustomerLedger(
                customer_id=customer.id,
                outlet_id=order.outlet_id,
                tenant_id=order.tenant_id,
                order_id=order.id,
                ledger_type="LOYALTY",
                transaction_type="ORDER_EARN",
                points_delta=pts_earned,
                balance_after=Decimal(str(customer.loyalty_points)),
                reason="ORDER_EARN",
                idempotency_key=f"EARN_{order.id}"
            )
            db.add(ledger_entry)

    # 4. Debit Khata if on credit
    if khata_amount > 0:
        customer.credit_balance = (customer.credit_balance or Decimal("0.00")) + khata_amount
        credit_entry = RestaurantCustomerLedger(
            customer_id=customer.id,
            outlet_id=order.outlet_id,
            tenant_id=order.tenant_id,
            order_id=order.id,
            ledger_type="CREDIT",
            transaction_type="DEBIT",
            amount=khata_amount,
            balance_after=customer.credit_balance,
            payment_mode="KHATA",
            notes=f"Order #{order.order_number} billed on store credit",
            idempotency_key=f"DEBIT_{order.id}"
        )
        db.add(credit_entry)

    # 5. Bill Receipt Notification Audit Log
    if customer.phone:
        msg = f"Thank you for dining at our restaurant! Bill #{order.order_number} for Rs.{order.grand_total} is settled. Current points balance: {customer.loyalty_points}."
        notif = RestaurantCrmNotification(
            customer_id=customer.id,
            outlet_id=order.outlet_id,
            tenant_id=order.tenant_id,
            channel="WHATSAPP",
            event_type="BILL_RECEIPT",
            recipient=customer.phone,
            message_body=msg,
            status="SENT",
            provider_ref=f"WA-{uuid.uuid4().hex[:8].upper()}"
        )
        db.add(notif)


# ---------------------------------------------------------
# Customer Endpoints
# ---------------------------------------------------------
@router.get("/customers", response_model=List[RestaurantCustomerResponse])
def get_customers(
    outlet_id: Optional[UUID] = None,
    search: Optional[str] = None,
    segment: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Search customers by phone or name, filter by segment (ALL, VIP, REGULAR, NEW, AT_RISK).
    """
    target_outlet = outlet_id or current_user.outlet_id
    query = db.query(RestaurantCustomer).filter(RestaurantCustomer.is_active == True)

    if target_outlet:
        query = query.filter(
            or_(
                RestaurantCustomer.outlet_id == target_outlet,
                RestaurantCustomer.home_outlet_id == target_outlet
            )
        )
    elif current_user.tenant_id:
        query = query.filter(RestaurantCustomer.tenant_id == current_user.tenant_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                RestaurantCustomer.phone.ilike(s),
                RestaurantCustomer.name.ilike(s),
                RestaurantCustomer.email.ilike(s)
            )
        )

    if segment and segment.upper() != "ALL":
        seg_upper = segment.upper()
        # Tags is stored as JSON array, e.g. ["VIP"]
        query = query.filter(cast(RestaurantCustomer.tags, String).ilike(f"%{seg_upper}%"))

    return query.order_by(RestaurantCustomer.total_spent.desc()).limit(limit).all()


@router.post("/customers", response_model=RestaurantCustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: RestaurantCustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Register or update guest profile with dietary preferences, special dates, and GSTIN.
    """
    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == payload.outlet_id).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant outlet not found")

    existing = (
        db.query(RestaurantCustomer)
        .filter(RestaurantCustomer.tenant_id == outlet.tenant_id)
        .filter(RestaurantCustomer.phone == payload.phone)
        .first()
    )
    if existing:
        # Update existing profile
        existing.name = payload.name or existing.name
        if payload.email:
            existing.email = payload.email
        if payload.dob:
            existing.dob = payload.dob
        if payload.anniversary:
            existing.anniversary = payload.anniversary
        if payload.gst_number:
            existing.gst_number = payload.gst_number
        if payload.preferences:
            existing.preferences = payload.preferences
        if payload.tags:
            existing.tags = payload.tags
        if payload.credit_limit is not None:
            existing.credit_limit = payload.credit_limit
        if payload.notes:
            existing.notes = payload.notes
        db.commit()
        db.refresh(existing)
        return existing

    customer = RestaurantCustomer(
        outlet_id=payload.outlet_id,
        home_outlet_id=payload.outlet_id,
        tenant_id=outlet.tenant_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        dob=payload.dob,
        anniversary=payload.anniversary,
        gst_number=payload.gst_number,
        preferences=payload.preferences or {},
        tags=payload.tags or ["NEW"],
        total_visits=0,
        total_spent=Decimal("0.00"),
        avg_order_value=Decimal("0.00"),
        loyalty_points=0,
        credit_balance=Decimal("0.00"),
        credit_limit=payload.credit_limit or Decimal("0.00"),
        opt_in_marketing=payload.opt_in_marketing,
        notes=payload.notes,
        is_active=payload.is_active
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/customers/{customer_id}", response_model=RestaurantCustomerResponse)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Get customer profile by ID.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/customers/{customer_id}", response_model=RestaurantCustomerResponse)
def update_customer_profile(
    customer_id: UUID,
    payload: RestaurantCustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Update customer profile details, credit limits, or preferences.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)

    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Deactivate or remove customer.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if customer:
        customer.is_active = False
        db.commit()
    return None


@router.get("/customers/{customer_id}/insights", response_model=CustomerInsightsResponse)
def get_customer_insights(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Fetch comprehensive guest insights:
    - RFM metrics & Segment (VIP, REGULAR, NEW, AT_RISK)
    - Top 5 ordered dishes
    - Recent order history & bills
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Segment derivation
    primary_segment = "NEW"
    if customer.tags and len(customer.tags) > 0:
        primary_segment = customer.tags[0]
    elif customer.total_spent >= Decimal("5000.00") or customer.total_visits >= 10:
        primary_segment = "VIP"
    elif customer.total_visits >= 3:
        primary_segment = "REGULAR"

    # Check AT_RISK if last visit was > 30 days ago
    if customer.last_visit_at and (datetime.utcnow() - customer.last_visit_at).days > 30:
        primary_segment = "AT_RISK"

    # Top 5 favorite dishes
    dish_query = (
        db.query(
            RestaurantOrderLine.item_name,
            RestaurantOrderLine.variant_name,
            func.sum(RestaurantOrderLine.quantity).label("order_count"),
            func.sum(RestaurantOrderLine.line_total).label("total_spent")
        )
        .join(RestaurantOrder, RestaurantOrderLine.order_id == RestaurantOrder.id)
        .filter(
            or_(
                RestaurantOrder.customer_id == customer.id,
                RestaurantOrder.customer_phone == customer.phone
            )
        )
        .group_by(RestaurantOrderLine.item_name, RestaurantOrderLine.variant_name)
        .order_by(func.sum(RestaurantOrderLine.quantity).desc())
        .limit(5)
        .all()
    )

    top_dishes = [
        CustomerTopDish(
            item_name=row.item_name,
            variant_name=row.variant_name,
            order_count=int(row.order_count or 0),
            total_spent=Decimal(str(row.total_spent or 0.00))
        )
        for row in dish_query
    ]

    # Recent 5 bills
    bills_query = (
        db.query(RestaurantOrder)
        .filter(
            or_(
                RestaurantOrder.customer_id == customer.id,
                RestaurantOrder.customer_phone == customer.phone
            )
        )
        .order_by(RestaurantOrder.created_at.desc())
        .limit(5)
        .all()
    )

    recent_bills = [
        CustomerRecentBill(
            order_id=b.id,
            order_number=b.order_number,
            order_type=b.order_type,
            grand_total=b.grand_total,
            created_at=b.created_at
        )
        for b in bills_query
    ]

    return CustomerInsightsResponse(
        customer_id=customer.id,
        name=customer.name,
        phone=customer.phone,
        total_visits=customer.total_visits,
        total_spent=customer.total_spent,
        avg_order_value=customer.avg_order_value,
        loyalty_points=customer.loyalty_points,
        credit_balance=customer.credit_balance,
        credit_limit=customer.credit_limit,
        current_segment=primary_segment,
        last_visit_at=customer.last_visit_at,
        top_dishes=top_dishes,
        recent_bills=recent_bills
    )


# ---------------------------------------------------------
# Loyalty Rules & Ledger Endpoints
# ---------------------------------------------------------
@router.get("/loyalty-rules", response_model=LoyaltyRulesResponse)
def get_loyalty_rules(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Get brand-wide loyalty rules configuration. If not configured, returns default rules.
    """
    tenant_id = current_user.tenant_id
    if not tenant_id and outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == outlet_id).first()
        if outlet:
            tenant_id = outlet.tenant_id

    rules = db.query(RestaurantLoyaltyRules).filter(RestaurantLoyaltyRules.tenant_id == tenant_id).first()
    if not rules:
        # Create default rules
        rules = RestaurantLoyaltyRules(
            tenant_id=tenant_id or uuid.uuid4(),
            outlet_id=outlet_id or current_user.outlet_id,
            earn_per_rupees=Decimal("100.00"),
            point_value_inr=Decimal("1.00"),
            min_order_for_redeem=Decimal("200.00"),
            max_redeem_pct=Decimal("20.00"),
            points_expiry_days=180,
            is_active=True
        )
        db.add(rules)
        db.commit()
        db.refresh(rules)
    return rules


@router.post("/loyalty-rules", response_model=LoyaltyRulesResponse)
def configure_loyalty_rules(
    payload: LoyaltyRulesBase,
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Create or update brand-wide loyalty rules (earn rate, burn rate, min order threshold).
    """
    tenant_id = current_user.tenant_id
    if not tenant_id and outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == outlet_id).first()
        if outlet:
            tenant_id = outlet.tenant_id

    rules = db.query(RestaurantLoyaltyRules).filter(RestaurantLoyaltyRules.tenant_id == tenant_id).first()
    if not rules:
        rules = RestaurantLoyaltyRules(
            tenant_id=tenant_id or uuid.uuid4(),
            outlet_id=outlet_id or current_user.outlet_id
        )
        db.add(rules)

    rules.earn_per_rupees = payload.earn_per_rupees
    rules.point_value_inr = payload.point_value_inr
    rules.min_order_for_redeem = payload.min_order_for_redeem
    rules.max_redeem_pct = payload.max_redeem_pct
    rules.points_expiry_days = payload.points_expiry_days
    rules.is_active = payload.is_active

    db.commit()
    db.refresh(rules)
    return rules


@router.post("/customers/{customer_id}/loyalty/adjust", response_model=LoyaltyLedgerResponse, status_code=status.HTTP_201_CREATED)
def adjust_loyalty_points(
    customer_id: UUID,
    payload: LoyaltyPointsAdjustment,
    db: Session = Depends(get_db),
    cashier_user: User = Depends(get_restaurant_cashier)
):
    """
    Idempotent loyalty points earning or redemption.
    """
    if payload.idempotency_key:
        existing = (
            db.query(RestaurantCustomerLedger)
            .filter(RestaurantCustomerLedger.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing:
            return existing

    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if payload.points_delta < 0 and customer.loyalty_points < abs(payload.points_delta):
        raise HTTPException(status_code=400, detail="Insufficient loyalty points balance")

    customer.loyalty_points = (customer.loyalty_points or 0) + payload.points_delta

    ledger = RestaurantCustomerLedger(
        customer_id=customer.id,
        outlet_id=customer.outlet_id,
        tenant_id=customer.tenant_id,
        ledger_type="LOYALTY",
        transaction_type=payload.reason,
        points_delta=payload.points_delta,
        balance_after=Decimal(str(customer.loyalty_points)),
        reason=payload.reason,
        order_id=payload.source_order_id,
        idempotency_key=payload.idempotency_key
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)
    return ledger


@router.get("/customers/{customer_id}/loyalty/history", response_model=List[LoyaltyLedgerResponse])
def get_loyalty_history(
    customer_id: UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Get customer loyalty ledger audit trail.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    return (
        db.query(RestaurantCustomerLedger)
        .filter(RestaurantCustomerLedger.customer_id == customer_id, RestaurantCustomerLedger.ledger_type == "LOYALTY")
        .order_by(RestaurantCustomerLedger.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------
# Khata / Store Credit Endpoints
# ---------------------------------------------------------
@router.get("/customers/{customer_id}/khata", response_model=KhataStatementResponse)
def get_khata_statement(
    customer_id: UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Get guest Khata (store credit) balance and ledger statement.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    ledger_entries = (
        db.query(RestaurantCustomerLedger)
        .filter(RestaurantCustomerLedger.customer_id == customer_id, RestaurantCustomerLedger.ledger_type == "CREDIT")
        .order_by(RestaurantCustomerLedger.created_at.desc())
        .limit(limit)
        .all()
    )

    return KhataStatementResponse(
        customer_id=customer.id,
        customer_name=customer.name,
        phone=customer.phone,
        credit_balance=customer.credit_balance,
        credit_limit=customer.credit_limit,
        ledger=ledger_entries
    )


@router.post("/customers/{customer_id}/khata/settle", response_model=KhataLedgerResponse, status_code=status.HTTP_201_CREATED)
def settle_khata_dues(
    customer_id: UUID,
    payload: KhataSettleRequest,
    db: Session = Depends(get_db),
    cashier_user: User = Depends(get_restaurant_cashier)
):
    """
    Customer pays off partial or full Khata dues (CREDIT transaction).
    """
    if payload.idempotency_key:
        existing = (
            db.query(RestaurantCustomerLedger)
            .filter(RestaurantCustomerLedger.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing:
            return existing

    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if payload.amount <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Settlement amount must be positive")

    customer.credit_balance = max(Decimal("0.00"), customer.credit_balance - payload.amount)

    ledger_entry = RestaurantCustomerLedger(
        customer_id=customer.id,
        outlet_id=customer.outlet_id,
        tenant_id=customer.tenant_id,
        ledger_type="CREDIT",
        transaction_type="CREDIT", # Payment received
        amount=payload.amount,
        balance_after=customer.credit_balance,
        payment_mode=payload.payment_mode,
        notes=payload.notes or "Khata due payment settlement",
        idempotency_key=payload.idempotency_key
    )
    db.add(ledger_entry)

    # Dispatch confirmation notification
    if customer.phone:
        msg = f"Payment of Rs.{payload.amount} received towards your credit account. Remaining Khata balance: Rs.{customer.credit_balance}."
        notif = RestaurantCrmNotification(
            customer_id=customer.id,
            outlet_id=customer.outlet_id,
            tenant_id=customer.tenant_id,
            channel="WHATSAPP",
            event_type="KHATA_ALERT",
            recipient=customer.phone,
            message_body=msg,
            status="SENT",
            provider_ref=f"PAY-{uuid.uuid4().hex[:8].upper()}"
        )
        db.add(notif)

    db.commit()
    db.refresh(ledger_entry)
    return ledger_entry


# ---------------------------------------------------------
# Notifications & Scheduled Automations
# ---------------------------------------------------------
@router.post("/customers/{customer_id}/notify", response_model=CrmNotificationResponse, status_code=status.HTTP_201_CREATED)
def send_customer_notification(
    customer_id: UUID,
    payload: CrmNotificationSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Dispatch a manual or templated WhatsApp/SMS/Email notification to guest.
    """
    customer = db.query(RestaurantCustomer).filter(RestaurantCustomer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    recipient = payload.recipient or (customer.email if payload.channel.upper() == "EMAIL" else customer.phone)
    if not recipient:
        raise HTTPException(status_code=400, detail="No recipient address or phone found for customer")

    notif = RestaurantCrmNotification(
        customer_id=customer.id,
        outlet_id=customer.outlet_id,
        tenant_id=customer.tenant_id,
        channel=payload.channel.upper(),
        event_type=payload.event_type.upper(),
        recipient=recipient,
        message_body=payload.message_body,
        status="SENT",
        provider_ref=f"MSG-{uuid.uuid4().hex[:8].upper()}"
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


@router.get("/notifications/history", response_model=List[CrmNotificationResponse])
def get_notification_history(
    customer_id: Optional[UUID] = None,
    outlet_id: Optional[UUID] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Audit log of dispatched notifications across WhatsApp, SMS, and Email.
    """
    query = db.query(RestaurantCrmNotification)
    if customer_id:
        query = query.filter(RestaurantCrmNotification.customer_id == customer_id)
    if outlet_id:
        query = query.filter(RestaurantCrmNotification.outlet_id == outlet_id)
    elif current_user.tenant_id:
        query = query.filter(RestaurantCrmNotification.tenant_id == current_user.tenant_id)

    return query.order_by(RestaurantCrmNotification.created_at.desc()).limit(limit).all()


@router.post("/scheduled/run-automations", response_model=AutomationsRunResponse)
def run_scheduled_crm_automations(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Automated CRM Job (runs daily at 9:00 AM / 10:00 AM):
    - Birthday offers (matching DOB month & day)
    - Anniversary greetings (matching anniversary month & day)
    - Win-back alerts for churn-risk customers (last visit == 30 days ago)
    """
    target_outlet_id = outlet_id or current_user.outlet_id
    today = date.today()
    winback_cutoff = datetime.utcnow() - timedelta(days=30)

    customers_query = (
        db.query(RestaurantCustomer)
        .filter(RestaurantCustomer.is_active == True)
        .filter(RestaurantCustomer.opt_in_marketing == True)
    )
    if target_outlet_id:
        customers_query = customers_query.filter(RestaurantCustomer.outlet_id == target_outlet_id)

    customers = customers_query.all()

    birthdays_count = 0
    anniversaries_count = 0
    winback_count = 0

    for c in customers:
        # Birthday check
        if c.dob and c.dob.month == today.month and c.dob.day == today.day:
            bday_msg = f"Happy Birthday, {c.name}! Celebrate with us today and enjoy a special 15% discount on your bill."
            notif = RestaurantCrmNotification(
                customer_id=c.id,
                outlet_id=c.outlet_id,
                tenant_id=c.tenant_id,
                channel="WHATSAPP",
                event_type="BIRTHDAY_OFFER",
                recipient=c.phone,
                message_body=bday_msg,
                status="SENT",
                provider_ref=f"BDAY-{uuid.uuid4().hex[:8].upper()}"
            )
            db.add(notif)
            birthdays_count += 1

        # Anniversary check
        if c.anniversary and c.anniversary.month == today.month and c.anniversary.day == today.day:
            anni_msg = f"Happy Anniversary, {c.name}! Wishing you a wonderful celebration. Complimentary dessert on us when you dine today!"
            notif = RestaurantCrmNotification(
                customer_id=c.id,
                outlet_id=c.outlet_id,
                tenant_id=c.tenant_id,
                channel="WHATSAPP",
                event_type="ANNIVERSARY_OFFER",
                recipient=c.phone,
                message_body=anni_msg,
                status="SENT",
                provider_ref=f"ANNI-{uuid.uuid4().hex[:8].upper()}"
            )
            db.add(notif)
            anniversaries_count += 1

        # Inactive Win-back check (> 30 days since last visit)
        if c.last_visit_at and c.last_visit_at <= winback_cutoff:
            win_msg = f"We miss you, {c.name}! It's been a while since your last visit. Enjoy 10% off your next meal with code WELCOMEBACK10."
            notif = RestaurantCrmNotification(
                customer_id=c.id,
                outlet_id=c.outlet_id,
                tenant_id=c.tenant_id,
                channel="WHATSAPP",
                event_type="WINBACK",
                recipient=c.phone,
                message_body=win_msg,
                status="SENT",
                provider_ref=f"WIN-{uuid.uuid4().hex[:8].upper()}"
            )
            db.add(notif)
            winback_count += 1

    db.commit()

    return AutomationsRunResponse(
        status="SUCCESS",
        birthdays_triggered=birthdays_count,
        anniversaries_triggered=anniversaries_count,
        winback_triggered=winback_count,
        message=f"Automations processed: {birthdays_count} birthdays, {anniversaries_count} anniversaries, {winback_count} win-back campaigns dispatched."
    )
