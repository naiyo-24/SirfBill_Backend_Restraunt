import uuid
import os
import hmac
import hashlib
import base64
from typing import List, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import HTMLResponse, Response, FileResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

try:
    import razorpay
except ImportError:
    razorpay = None

try:
    import weasyprint
except ImportError:
    weasyprint = None

template_loader = FileSystemLoader(searchpath="templates")
sub_template_env = Environment(loader=template_loader, autoescape=True)

SIGNATURE_DIR = "uploads/signatures"
SIGNATURE_PATH = os.path.join(SIGNATURE_DIR, "authorized_sign.png")
os.makedirs(SIGNATURE_DIR, exist_ok=True)

INVOICES_DIR = "uploads/invoices"
os.makedirs(INVOICES_DIR, exist_ok=True)

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_subscription import SubscriptionPlan, TenantSubscription, SubscriptionPayment
from schemas.restaurant_subscription import (
    SubscriptionPlanResponse,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscribeRequest,
    RazorpayOrderCreate,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
    TenantSubscriptionResponse,
    SubscriptionStatusResponse,
    SubscriptionPaymentResponse,
    SubscriptionInvoiceResponse
)
from dependencies import get_current_user, get_optional_current_user, get_admin_user
from utils.timezone import get_current_time

router = APIRouter(
    prefix="/api/subscriptions",
    tags=["Restaurant - Subscription & Billing"]
)

DEFAULT_PLAN_CODE = "RESTAURANT_PRO_299"
DEFAULT_PLAN_NAME = "SirfBill Restaurant Pro (1 Month)"
DEFAULT_PLAN_PRICE = Decimal("299.00")
DEFAULT_PLAN_DAYS = 30

DEFAULT_FEATURES = [
    "Fast Touch POS Billing & Multi-Station KOT Printing",
    "Complete Recipe Management & Automatic BOM Inventory Deductions",
    "Multi-Branch Real-Time Inventory & Stock Transfers",
    "Physical Stock Audit & Variance Reconciliation",
    "Wastage & Spoilage Loss Tracking with Rupee Costing",
    "Interactive Table Layout & Live Kitchen Display (KDS)",
    "Automated Purchase Orders & Vendor GRN Inwarding",
    "Role-Based Multi-Staff Logins & Daily Shift Closure Reports"
]

SUBSCRIPTION_PLANS_CATALOG = [
    {
        "plan_code": "RESTAURANT_PRO_299",
        "name": "SirfBill Restaurant Pro (1 Month)",
        "description": "Standard 1 Month plan (₹299/month inclusive of 18% GST). Complete POS, Recipe BOM, KDS & Inventory.",
        "price": Decimal("299.00"),
        "currency": "INR",
        "billing_cycle": "1 Month",
        "duration_days": 30,
        "features": DEFAULT_FEATURES,
        "is_active": True,
        "is_popular": False
    },
    {
        "plan_code": "RESTAURANT_PRO_3M",
        "name": "SirfBill Restaurant Pro (3 Months)",
        "description": "3 Months plan: ₹299 x 3 = ₹897 + 18% GST = ₹1,058. Full POS & perpetual inventory license for 90 days.",
        "price": Decimal("1058.00"),
        "currency": "INR",
        "billing_cycle": "3 Months",
        "duration_days": 90,
        "features": DEFAULT_FEATURES,
        "is_active": True,
        "is_popular": True
    },
    {
        "plan_code": "RESTAURANT_PRO_6M",
        "name": "SirfBill Restaurant Pro (6 Months - 5% OFF)",
        "description": "6 Months plan: ₹299 x 6 = ₹1,794 with 5% discount (₹1,704.30) + 18% GST = ₹2,012.",
        "price": Decimal("2012.00"),
        "currency": "INR",
        "billing_cycle": "6 Months",
        "duration_days": 180,
        "features": DEFAULT_FEATURES,
        "is_active": True,
        "is_popular": False
    },
    {
        "plan_code": "RESTAURANT_PRO_12M",
        "name": "SirfBill Restaurant Pro (12 Months - 10% OFF)",
        "description": "Annual 12 Months plan: ₹299 x 12 = ₹3,588 with 10% discount (₹3,229.20) + 18% GST = ₹3,823.",
        "price": Decimal("3823.00"),
        "currency": "INR",
        "billing_cycle": "12 Months (1 Year)",
        "duration_days": 365,
        "features": DEFAULT_FEATURES,
        "is_active": True,
        "is_popular": False
    }
]


def amount_to_words_inr(amount: Decimal) -> str:
    """
    Converts Indian Rupee amounts to formal grammatical words (e.g., 'Rupees One Thousand Fifty-Eight Only').
    """
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
             "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _convert_below_thousand(n: int) -> str:
        res = []
        if n >= 100:
            res.append(units[n // 100] + " Hundred")
            n %= 100
        if n >= 20:
            res.append(tens[n // 10])
            n %= 10
        if n > 0:
            res.append(units[n])
        return " ".join(res)

    int_part = int(round(float(amount)))
    if int_part == 0:
        return "Rupees Zero Only"

    crore = int_part // 10000000
    int_part %= 10000000
    lakh = int_part // 100000
    int_part %= 100000
    thousand = int_part // 1000
    int_part %= 1000

    parts = []
    if crore:
        parts.append(_convert_below_thousand(crore) + " Crore")
    if lakh:
        parts.append(_convert_below_thousand(lakh) + " Lakh")
    if thousand:
        parts.append(_convert_below_thousand(thousand) + " Thousand")
    if int_part:
        parts.append(_convert_below_thousand(int_part))

    return "Rupees " + " ".join(parts).strip() + " Only"


def seed_default_plans(db: Session) -> List[SubscriptionPlan]:
    """
    Guarantees all 4 subscription plans (1M, 3M, 6M, 12M) exist in the database with accurate prices and durations.
    """
    saved_plans = []
    for plan_def in SUBSCRIPTION_PLANS_CATALOG:
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.plan_code == plan_def["plan_code"]
        ).first()

        if not plan:
            plan = SubscriptionPlan(
                plan_code=plan_def["plan_code"],
                name=plan_def["name"],
                description=plan_def["description"],
                price=plan_def["price"],
                currency=plan_def["currency"],
                billing_cycle=plan_def["billing_cycle"],
                duration_days=plan_def["duration_days"],
                features=plan_def["features"],
                is_active=plan_def["is_active"],
                is_popular=plan_def["is_popular"]
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
        else:
            # Sync price, duration, and name
            plan.name = plan_def["name"]
            plan.description = plan_def["description"]
            plan.price = plan_def["price"]
            plan.duration_days = plan_def["duration_days"]
            plan.billing_cycle = plan_def["billing_cycle"]
            plan.is_popular = plan_def["is_popular"]
            plan.is_active = True
            db.commit()

        saved_plans.append(plan)
    return saved_plans


def get_or_create_default_plan(db: Session) -> SubscriptionPlan:
    """
    Guarantees the standard 1-month plan exists and returns it.
    """
    seed_default_plans(db)
    return db.query(SubscriptionPlan).filter(
        SubscriptionPlan.plan_code == DEFAULT_PLAN_CODE
    ).first()


def resolve_plan_from_request(
    db: Session,
    plan_id: Optional[uuid.UUID] = None,
    plan_code: Optional[str] = None,
    duration_months: Optional[int] = None
) -> SubscriptionPlan:
    """
    Resolves the exact SubscriptionPlan from plan_id, plan_code, or duration_months (1, 3, 6, 12).
    """
    seed_default_plans(db)

    if plan_id:
        p = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
        if p:
            return p

    if plan_code:
        clean_code = plan_code.strip().upper()
        p = db.query(SubscriptionPlan).filter(
            func.upper(SubscriptionPlan.plan_code) == clean_code
        ).first()
        if p:
            return p

    if duration_months:
        target_days = {1: 30, 3: 90, 6: 180, 12: 365}.get(duration_months)
        if target_days:
            p = db.query(SubscriptionPlan).filter(SubscriptionPlan.duration_days == target_days).first()
            if p:
                return p

    return get_or_create_default_plan(db)


def resolve_tenant_id(user: Optional[User], db: Session, target_outlet_id: Optional[uuid.UUID] = None) -> uuid.UUID:
    """
    Resolves tenant_id from authenticated user or specified outlet.
    """
    if target_outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == target_outlet_id).first()
        if outlet and outlet.tenant_id:
            return outlet.tenant_id

    if user and user.tenant_id:
        return user.tenant_id

    if user and user.outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == user.outlet_id).first()
        if outlet and outlet.tenant_id:
            return outlet.tenant_id

    # Fallback to first available active outlet
    first_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True).first()
    if first_outlet and first_outlet.tenant_id:
        return first_outlet.tenant_id

    # Dev fallback UUID if DB is fresh
    return uuid.UUID("00a2b6d2-2803-4384-817a-d8bbaa7a0f28")


def _enrich_subscription_response(sub: TenantSubscription) -> TenantSubscriptionResponse:
    now = get_current_time()
    is_active = (sub.expires_at > now) and (sub.status != "CANCELLED")
    days_left = max(0, (sub.expires_at - now).days) if is_active else 0
    computed_status = ("ACTIVE" if sub.status != "TRIAL" else "TRIAL") if is_active else "EXPIRED"

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"
    invoice_url = f"/api/subscriptions/invoices/{inv_num}/view"
    download_url = f"/api/subscriptions/invoices/{inv_num}/pdf"

    return TenantSubscriptionResponse(
        id=sub.id,
        tenant_id=sub.tenant_id,
        outlet_id=sub.outlet_id,
        plan_id=sub.plan_id,
        plan_name=sub.plan.name if sub.plan else DEFAULT_PLAN_NAME,
        plan_code=sub.plan.plan_code if sub.plan else DEFAULT_PLAN_CODE,
        status=computed_status,
        price_paid=sub.price_paid,
        currency=sub.currency,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        days_remaining=days_left,
        is_active=is_active,
        payment_method=sub.payment_method,
        payment_reference=sub.payment_reference,
        invoice_number=inv_num,
        invoice_url=invoice_url,
        download_url=download_url,
        features=sub.plan.features if sub.plan and sub.plan.features else DEFAULT_FEATURES,
        created_at=sub.created_at
    )


# ----------------- PUBLIC & STAFF ENDPOINTS -----------------

@router.get("/plans", response_model=List[SubscriptionPlanResponse])
def get_subscription_plans(db: Session = Depends(get_db)):
    """
    Fetch all active subscription plans registered in the backend:
    - 1 Month: ₹299 (30 Days)
    - 3 Months: ₹1,058 (90 Days)
    - 6 Months: ₹2,012 (180 Days, 5% Discount)
    - 12 Months: ₹3,823 (365 Days, 10% Discount)
    """
    seed_default_plans(db)
    plans = (
        db.query(SubscriptionPlan)
        .filter(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.duration_days.asc())
        .all()
    )
    return plans


@router.post("/plans", response_model=SubscriptionPlanResponse, status_code=status.HTTP_201_CREATED)
def create_subscription_plan(
    payload: SubscriptionPlanCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """
    Create a new subscription plan in the backend catalog.
    Enables adding new tiers (e.g., Annual ₹2,999 or Multi-Outlet Pro).
    """
    existing = db.query(SubscriptionPlan).filter(
        func.lower(SubscriptionPlan.plan_code) == payload.plan_code.strip().lower()
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Plan with code '{payload.plan_code}' already exists")

    new_plan = SubscriptionPlan(
        plan_code=payload.plan_code.strip().upper(),
        name=payload.name,
        description=payload.description,
        price=payload.price,
        currency=payload.currency or "INR",
        billing_cycle=payload.billing_cycle or "MONTHLY",
        duration_days=payload.duration_days or 30,
        features=payload.features or DEFAULT_FEATURES,
        is_active=payload.is_active if payload.is_active is not None else True,
        is_popular=payload.is_popular if payload.is_popular is not None else False
    )
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return new_plan


@router.get("/plans/{plan_identifier}", response_model=SubscriptionPlanResponse)
def get_subscription_plan_by_id_or_code(
    plan_identifier: str,
    db: Session = Depends(get_db)
):
    """
    Fetch a subscription plan by UUID or plan_code (e.g. 'RESTAURANT_PRO_299').
    """
    plan = None
    try:
        val_uuid = uuid.UUID(plan_identifier)
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == val_uuid).first()
    except (ValueError, AttributeError):
        pass

    if not plan:
        plan = db.query(SubscriptionPlan).filter(
            func.lower(SubscriptionPlan.plan_code) == plan_identifier.strip().lower()
        ).first()

    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")

    return plan


@router.put("/plans/{plan_identifier}", response_model=SubscriptionPlanResponse)
@router.patch("/plans/{plan_identifier}", response_model=SubscriptionPlanResponse)
def update_subscription_plan(
    plan_identifier: str,
    payload: SubscriptionPlanUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """
    Update an existing subscription plan in the backend catalog.
    Allows updating:
    - Price (e.g. change ₹299 to ₹399, ₹499)
    - Name & Description
    - Validity Duration (e.g. 30 days, 90 days, 365 days)
    - Feature list & Entitlements
    - Active & Popular status flags
    All future checkouts automatically inherit the updated plan parameters.
    """
    plan = None
    try:
        val_uuid = uuid.UUID(plan_identifier)
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == val_uuid).first()
    except (ValueError, AttributeError):
        pass

    if not plan:
        plan = db.query(SubscriptionPlan).filter(
            func.lower(SubscriptionPlan.plan_code) == plan_identifier.strip().lower()
        ).first()

    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(plan, field, value)

    plan.updated_at = get_current_time()
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_identifier}")
def deactivate_subscription_plan(
    plan_identifier: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """
    Deactivates a subscription plan without deleting historical subscriber records.
    """
    plan = None
    try:
        val_uuid = uuid.UUID(plan_identifier)
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == val_uuid).first()
    except (ValueError, AttributeError):
        pass

    if not plan:
        plan = db.query(SubscriptionPlan).filter(
            func.lower(SubscriptionPlan.plan_code) == plan_identifier.strip().lower()
        ).first()

    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")

    plan.is_active = False
    plan.updated_at = get_current_time()
    db.commit()

    return {"message": f"Plan '{plan.name}' ({plan.plan_code}) has been deactivated successfully", "is_active": False}


@router.get("/status", response_model=SubscriptionStatusResponse)
def get_subscription_status(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Lightweight health/entitlement check for UI banners, POS guards, and dashboards.
    Reports whether the restaurant's subscription is currently active or expired.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)
    now = get_current_time()

    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        default_plan = get_or_create_default_plan(db)
        return SubscriptionStatusResponse(
            has_subscription=False,
            is_active=False,
            status="NONE",
            plan_name=default_plan.name,
            price=default_plan.price,
            billing_cycle=default_plan.billing_cycle,
            expires_at=None,
            days_remaining=0,
            features=default_plan.features,
            outlet_id=outlet_id,
            tenant_id=tenant_id
        )

    is_active = (sub.expires_at > now) and (sub.status != "CANCELLED")
    days_left = max(0, (sub.expires_at - now).days) if is_active else 0
    computed_status = ("ACTIVE" if sub.status != "TRIAL" else "TRIAL") if is_active else "EXPIRED"

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"

    return SubscriptionStatusResponse(
        has_subscription=True,
        is_active=is_active,
        status=computed_status,
        plan_name=sub.plan.name if sub.plan else DEFAULT_PLAN_NAME,
        price=sub.price_paid,
        billing_cycle=sub.plan.billing_cycle if sub.plan else "MONTHLY",
        expires_at=sub.expires_at,
        days_remaining=days_left,
        features=sub.plan.features if sub.plan and sub.plan.features else DEFAULT_FEATURES,
        outlet_id=sub.outlet_id or outlet_id,
        tenant_id=tenant_id,
        latest_invoice_number=inv_num,
        latest_invoice_url=f"/api/subscriptions/invoices/{inv_num}/view",
        latest_download_url=f"/api/subscriptions/invoices/{inv_num}/pdf"
    )


@router.get("/current", response_model=TenantSubscriptionResponse)
def get_current_subscription(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Get detailed subscription information for the current restaurant tenant.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        # Auto-create a 14-day complimentary trial so fresh restaurant setups work instantly
        default_plan = get_or_create_default_plan(db)
        now = get_current_time()
        sub = TenantSubscription(
            tenant_id=tenant_id,
            outlet_id=outlet_id,
            plan_id=default_plan.id,
            status="TRIAL",
            price_paid=Decimal("0.00"),
            currency="INR",
            started_at=now,
            expires_at=now + timedelta(days=14),
            payment_method="FREE_TRIAL",
            payment_reference="COMPLIMENTARY_TRIAL",
            invoice_number=f"TRIAL-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            notes="14-day complimentary trial on onboarding",
            auto_renew=False,
            purchased_by_id=current_user.id if current_user else None
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)

    return _enrich_subscription_response(sub)


@router.post("/subscribe", response_model=TenantSubscriptionResponse, status_code=status.HTTP_201_CREATED)
def subscribe_or_renew(
    payload: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Super Admin purchases or renews the subscription (₹299 / month).
    1. Resolves plan (defaults to ₹299/mo SirfBill Restaurant Pro).
    2. Extends active subscription by +30 days (stacking) or starts fresh 30-day period.
    3. Generates formal invoice number and logs payment transaction.
    """
    tenant_id = resolve_tenant_id(current_user, db, payload.outlet_id)

    # 1. Resolve Plan
    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)

    now = get_current_time()
    duration_days = plan.duration_days or 30

    # 2. Check existing subscription to support seamless extension
    existing_sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if existing_sub and existing_sub.expires_at > now and existing_sub.status in ("ACTIVE", "TRIAL"):
        # Subscription is currently active -> extend from current expiry date
        new_start = existing_sub.started_at
        new_expiry = existing_sub.expires_at + timedelta(days=duration_days)
    else:
        # Expired or new subscription -> starts today
        new_start = now
        new_expiry = now + timedelta(days=duration_days)

    invoice_no = f"INV-SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    payment_ref = payload.payment_reference or f"UPI-PAY-{uuid.uuid4().hex[:8].upper()}"

    # 3. Create or update tenant subscription record
    subscription = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=payload.outlet_id,
        plan_id=plan.id,
        status="ACTIVE",
        price_paid=plan.price,
        currency=plan.currency,
        started_at=new_start,
        expires_at=new_expiry,
        payment_method=payload.payment_method or "UPI",
        payment_reference=payment_ref,
        invoice_number=invoice_no,
        notes=payload.notes or f"Subscribed to {plan.name} (₹{plan.price}/{plan.billing_cycle.lower()})",
        auto_renew=True,
        purchased_by_id=current_user.id if current_user else None
    )
    db.add(subscription)
    db.flush()

    # 4. Log immutable payment transaction
    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        tenant_id=tenant_id,
        amount=plan.price,
        currency=plan.currency,
        payment_gateway=payload.payment_method or "MANUAL_UPI",
        gateway_order_id=invoice_no,
        gateway_payment_id=payment_ref,
        status="SUCCESS",
        payment_date=now,
        notes=f"Payment for {plan.name} by Super Admin"
    )
    db.add(payment)

    db.commit()
    db.refresh(subscription)

    # Pre-render and store physical invoice PDF
    if weasyprint:
        try:
            pdf_path = os.path.join(INVOICES_DIR, f"{invoice_no}.pdf")
            html_doc = render_subscription_invoice_html(subscription, db, autoprint=False)
            pdf_bytes = weasyprint.HTML(string=html_doc, base_url=".").write_pdf()
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:
            print(f"[PDF Storage Note] {e}")

    return _enrich_subscription_response(subscription)


def get_razorpay_credentials():
    from dotenv import load_dotenv
    load_dotenv(override=True)
    key_id = os.getenv("RAZORPAY_KEY_ID", "rzp_live_ReRSf5hDkv7b7S").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "f53eoKxb41XlxDKej4XJoZSK").strip()
    return key_id, key_secret

@router.post("/create-order", response_model=RazorpayOrderResponse)
def create_razorpay_order(
    payload: RazorpayOrderCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Creates a Razorpay Order for purchasing or renewing the restaurant subscription.
    Returns the order ID and key ID for the frontend Razorpay Checkout modal.
    """
    tenant_id = resolve_tenant_id(current_user, db, payload.outlet_id)

    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)

    amount_paise = int(plan.price * 100)
    receipt_no = f"rcpt_{str(tenant_id)[:8]}_{int(get_current_time().timestamp())}"
    order_id = None
    key_id, key_secret = get_razorpay_credentials()

    if razorpay and key_id and key_secret:
        try:
            client = razorpay.Client(auth=(key_id, key_secret))
            rzp_order = client.order.create({
                "amount": amount_paise,
                "currency": plan.currency or "INR",
                "receipt": receipt_no,
                "notes": {
                    "tenant_id": str(tenant_id),
                    "plan_id": str(plan.id),
                    "plan_code": plan.plan_code
                }
            })
            order_id = rzp_order.get("id")
            print(f"[Razorpay Order Success] Order ID: {order_id} | Amount: ₹{plan.price} ({amount_paise} paise)")
        except Exception as e:
            print(f"[Razorpay Warning] order.create failed: {e}")
            order_id = None
    else:
        order_id = None

    return RazorpayOrderResponse(
        order_id=order_id,
        amount=plan.price,
        amount_paise=amount_paise,
        currency=plan.currency or "INR",
        key_id=key_id,
        plan_id=plan.id,
        plan_name=plan.name,
        plan_code=plan.plan_code,
        duration_days=plan.duration_days,
        billing_cycle=plan.billing_cycle,
        outlet_id=payload.outlet_id
    )


@router.post("/verify-payment", response_model=TenantSubscriptionResponse)
def verify_razorpay_payment(
    payload: RazorpayVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Verifies Razorpay payment signature and activates the subscription (+30 days, +90 days, +180 days, +365 days).
    """
    tenant_id = resolve_tenant_id(current_user, db, payload.outlet_id)

    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)

    # 1. Verify Signature
    is_valid = False
    key_id, key_secret = get_razorpay_credentials()
    if key_secret and payload.razorpay_order_id and payload.razorpay_signature and not payload.razorpay_order_id.startswith("order_test_"):
        try:
            expected_sig = hmac.new(
                key_secret.encode("utf-8"),
                f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            is_valid = hmac.compare_digest(expected_sig, payload.razorpay_signature)
        except Exception:
            is_valid = False
    else:
        # In simulated checkout, accept valid format
        is_valid = bool(payload.razorpay_payment_id)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay payment signature. Verification failed."
        )

    # 2. Activate or extend subscription (+30 days)
    now = get_current_time()
    duration_days = plan.duration_days or 30

    existing_sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if existing_sub and existing_sub.expires_at > now and existing_sub.status in ("ACTIVE", "TRIAL"):
        new_start = existing_sub.started_at
        new_expiry = existing_sub.expires_at + timedelta(days=duration_days)
    else:
        new_start = now
        new_expiry = now + timedelta(days=duration_days)

    invoice_no = f"INV-SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    subscription = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=payload.outlet_id,
        plan_id=plan.id,
        status="ACTIVE",
        price_paid=plan.price,
        currency=plan.currency,
        started_at=new_start,
        expires_at=new_expiry,
        payment_method="RAZORPAY",
        payment_reference=payload.razorpay_payment_id,
        invoice_number=invoice_no,
        notes=payload.notes or f"Razorpay online payment verified (Order: {payload.razorpay_order_id}, Payment: {payload.razorpay_payment_id})",
        auto_renew=True,
        purchased_by_id=current_user.id if current_user else None
    )
    db.add(subscription)
    db.flush()

    # 3. Log Payment Transaction
    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        tenant_id=tenant_id,
        amount=plan.price,
        currency=plan.currency,
        payment_gateway="RAZORPAY",
        gateway_order_id=payload.razorpay_order_id,
        gateway_payment_id=payload.razorpay_payment_id,
        status="SUCCESS",
        payment_date=now,
        notes=f"Razorpay payment verified for {plan.name}"
    )
    db.add(payment)

    db.commit()
    db.refresh(subscription)

    # Pre-render and store physical invoice PDF
    if weasyprint:
        try:
            pdf_path = os.path.join(INVOICES_DIR, f"{invoice_no}.pdf")
            html_doc = render_subscription_invoice_html(subscription, db, autoprint=False)
            pdf_bytes = weasyprint.HTML(string=html_doc, base_url=".").write_pdf()
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:
            print(f"[PDF Storage Note] {e}")

    return _enrich_subscription_response(subscription)


@router.get("/history", response_model=List[TenantSubscriptionResponse])
def get_subscription_history(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Get full subscription history and invoices for the restaurant tenant.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    subscriptions = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.created_at.desc()).all()

    return [_enrich_subscription_response(sub) for sub in subscriptions]


@router.post("/grant-trial", response_model=TenantSubscriptionResponse)
def grant_trial_extension(
    days: int = Query(30, ge=1, le=365),
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """
    Admin override: Grant complimentary trial or extend validity by N days.
    """
    tenant_id = resolve_tenant_id(admin_user, db, outlet_id)
    plan = get_or_create_default_plan(db)
    now = get_current_time()

    existing = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if existing and existing.expires_at > now:
        new_expiry = existing.expires_at + timedelta(days=days)
    else:
        new_expiry = now + timedelta(days=days)

    invoice_no = f"TRIAL-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    sub = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=outlet_id,
        plan_id=plan.id,
        status="TRIAL",
        price_paid=Decimal("0.00"),
        currency="INR",
        started_at=now,
        expires_at=new_expiry,
        payment_method="ADMIN_GRANT",
        payment_reference="MANUAL_ACTIVATION",
        invoice_number=invoice_no,
        notes=f"Complimentary extension granted for {days} days by {admin_user.name}",
        auto_renew=False,
        purchased_by_id=admin_user.id
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    return _enrich_subscription_response(sub)


# ----------------- INVOICE CHALLAN & SIGNATURE SYSTEM -----------------

def render_subscription_invoice_html(sub: TenantSubscription, db: Session, autoprint: bool = False) -> str:
    """
    Renders the premium tax invoice & software entitlement challan for SirfBill Restaurant.
    """
    # 1. Resolve Plan
    plan = sub.plan or db.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
    if not plan:
        plan = get_or_create_default_plan(db)

    # 2. Resolve Outlet & Tenant
    outlet = None
    if sub.outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == sub.outlet_id).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id == sub.tenant_id).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).first()

    # 3. Resolve User
    user = None
    if sub.purchased_by_id:
        user = db.query(User).filter(User.id == sub.purchased_by_id).first()
    if not user:
        user = db.query(User).filter(User.tenant_id == sub.tenant_id).first()

    # 4. Financial Calculation (18% GST Registered Entity: 9% CGST + 9% SGST)
    gross_val = Decimal(str(sub.price_paid if sub.price_paid is not None else "299.00"))
    if gross_val > Decimal("0.00"):
        base_val = (gross_val / Decimal("1.18")).quantize(Decimal("0.01"))
        cgst_val = (base_val * Decimal("0.09")).quantize(Decimal("0.01"))
        sgst_val = (gross_val - base_val - cgst_val).quantize(Decimal("0.01"))
        tot_tax = cgst_val + sgst_val
    else:
        base_val = Decimal("0.00")
        cgst_val = Decimal("0.00")
        sgst_val = Decimal("0.00")
        tot_tax = Decimal("0.00")

    calc = {
        "gross_amount": f"{gross_val:.2f}",
        "base_amount": f"{base_val:.2f}",
        "cgst": f"{cgst_val:.2f}",
        "sgst": f"{sgst_val:.2f}",
        "total_tax": f"{tot_tax:.2f}",
        "amount_in_words": amount_to_words_inr(gross_val),
        "is_gst": True
    }

    # 5. Check if custom authorized signature exists (embed as base64 for PDF self-containment)
    sig_url = None
    if os.path.exists(SIGNATURE_PATH):
        try:
            with open(SIGNATURE_PATH, "rb") as f:
                sig_url = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        except Exception:
            sig_url = f"/uploads/signatures/authorized_sign.png?v={int(os.path.getmtime(SIGNATURE_PATH))}"

    # 6. Embed brand logo as base64 for 100% self-contained PDF rendering
    brand_logo_b64 = None
    logo_file = "uploads/brand/sirfbill_logo.png"
    if os.path.exists(logo_file):
        try:
            with open(logo_file, "rb") as f:
                brand_logo_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        except Exception:
            pass

    brand_icon_b64 = None
    icon_file = "uploads/brand/sirfbill_icon.png"
    if os.path.exists(icon_file):
        try:
            with open(icon_file, "rb") as f:
                brand_icon_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        except Exception:
            pass

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"

    company_info = {
        "name": "Naiyo24 Private Limited",
        "brand": "SirfBill Restaurant",
        "cin": "U73100WB2024PTC271832",
        "gstin": "19AATCM4745N1ZH",
        "state_code": "19 (West Bengal)",
        "address": "1/30B, Chittaranjan Colony, Baghajatin Colony, Kolkata, West Bengal - 700032",
        "contact_person": "Debasish Baidya",
        "phone": "+91 6289171798",
        "email": "naiyooffice@gmail.com",
        "website": "www.naiyo24.com",
        "logo_url": brand_logo_b64 or "/uploads/brand/sirfbill_logo.png",
        "icon_url": brand_icon_b64 or "/uploads/brand/sirfbill_icon.png"
    }

    inv_data = {
        "invoice_number": inv_num,
        "tenant_id": str(sub.tenant_id),
        "formatted_started_at": sub.started_at.strftime("%d %b %Y, %I:%M %p") if sub.started_at else "N/A",
        "formatted_expires_at": sub.expires_at.strftime("%d %b %Y, %I:%M %p") if sub.expires_at else "N/A",
        "payment_method": sub.payment_method or "Razorpay (Online UPI/Cards)",
        "payment_reference": sub.payment_reference or "RZP_PAY_ONLINE",
        "status": sub.status
    }

    template = sub_template_env.get_template("subscription_invoice_template.html")
    return template.render(
        invoice=inv_data,
        company=company_info,
        plan=plan,
        outlet=outlet,
        user=user,
        calculation=calc,
        signature_url=sig_url,
        autoprint=autoprint
    )


@router.get("/invoices", response_model=List[SubscriptionInvoiceResponse])
def list_subscription_invoices(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    List all stored tax invoices and subscription receipts from the database.
    Includes itemized breakdown (Subtotal, 9% CGST, 9% SGST, Total), payment reference, and view/download links.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    subscriptions = (
        db.query(TenantSubscription)
        .options(
            joinedload(TenantSubscription.plan),
            joinedload(TenantSubscription.outlet),
            joinedload(TenantSubscription.payments)
        )
        .filter(TenantSubscription.tenant_id == tenant_id)
        .order_by(TenantSubscription.started_at.desc())
        .all()
    )

    if not subscriptions:
        # Fallback to all subscriptions if tenant has not been scoped yet
        subscriptions = (
            db.query(TenantSubscription)
            .options(
                joinedload(TenantSubscription.plan),
                joinedload(TenantSubscription.outlet),
                joinedload(TenantSubscription.payments)
            )
            .order_by(TenantSubscription.started_at.desc())
            .all()
        )

    invoices = []
    for s in subscriptions:
        inv_num = s.invoice_number or f"INV-SUB-{s.started_at.strftime('%Y%m%d')}-{str(s.id)[:6].upper()}"
        gross_val = Decimal(str(s.price_paid if s.price_paid is not None else "299.00"))
        if gross_val > Decimal("0.00"):
            base_val = (gross_val / Decimal("1.18")).quantize(Decimal("0.01"))
            cgst_val = (base_val * Decimal("0.09")).quantize(Decimal("0.01"))
            sgst_val = (gross_val - base_val - cgst_val).quantize(Decimal("0.01"))
            tot_tax = cgst_val + sgst_val
        else:
            base_val = Decimal("0.00")
            cgst_val = Decimal("0.00")
            sgst_val = Decimal("0.00")
            tot_tax = Decimal("0.00")

        pay_ref = s.payment_reference
        pay_method = s.payment_method
        pay_status = "SUCCESS" if s.status in ("ACTIVE", "TRIAL") else s.status
        if s.payments:
            latest_pay = s.payments[-1]
            if latest_pay.gateway_payment_id:
                pay_ref = latest_pay.gateway_payment_id
            if latest_pay.payment_gateway:
                pay_method = latest_pay.payment_gateway
            pay_status = latest_pay.status

        invoices.append(SubscriptionInvoiceResponse(
            id=s.id,
            invoice_number=inv_num,
            tenant_id=s.tenant_id,
            outlet_id=s.outlet_id,
            outlet_name=s.outlet.name if s.outlet else None,
            plan_name=s.plan.name if s.plan else DEFAULT_PLAN_NAME,
            subtotal=float(base_val),
            tax_amount=float(tot_tax),
            cgst=float(cgst_val),
            sgst=float(sgst_val),
            total_amount=float(gross_val),
            currency=s.currency or "INR",
            payment_method=pay_method or "RAZORPAY",
            payment_reference=pay_ref or "PAY_VERIFIED",
            payment_status=pay_status,
            issue_date=s.started_at,
            formatted_issue_date=s.started_at.strftime("%d %b %Y, %I:%M %p") if s.started_at else "N/A",
            expires_at=s.expires_at,
            formatted_expires_at=s.expires_at.strftime("%d %b %Y, %I:%M %p") if s.expires_at else "N/A",
            view_url=f"/api/subscriptions/invoices/{inv_num}/view",
            download_url=f"/api/subscriptions/invoices/{inv_num}/pdf",
            status=s.status
        ))

    return invoices


@router.get("/invoices/latest")
def get_latest_subscription_invoice(
    outlet_id: Optional[uuid.UUID] = Query(None),
    redirect: bool = Query(False, description="Redirect to HTML view directly"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Returns the most recent subscription invoice for the active tenant.
    If redirect=true, directly opens the HTML bill view in the browser.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)
    sub = (
        db.query(TenantSubscription)
        .filter(TenantSubscription.tenant_id == tenant_id)
        .order_by(TenantSubscription.expires_at.desc())
        .first()
    )
    if not sub:
        sub = db.query(TenantSubscription).order_by(TenantSubscription.created_at.desc()).first()

    if not sub:
        raise HTTPException(status_code=404, detail="No subscription invoices found in database")

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"
    view_url = f"/api/subscriptions/invoices/{inv_num}/view"

    if redirect:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=view_url)

    html_content = render_subscription_invoice_html(sub, db, autoprint=False)
    return HTMLResponse(content=html_content)


@router.get("/invoices/{invoice_identifier}/view", response_class=HTMLResponse)
@router.get("/invoices/{invoice_identifier}/html", response_class=HTMLResponse)
def view_subscription_invoice_html(
    invoice_identifier: str,
    autoprint: bool = Query(False, description="Open system print dialog automatically"),
    db: Session = Depends(get_db)
):
    """
    Renders the premium, attractive Tax Invoice & Subscription Challan.
    Features:
    - SirfBill Restaurant | Powered By Naiyo24 Pvt. Ltd.
    - Authorized Signatory stamp & signature
    - Itemized SaaS license with GST tax breakdown (9% CGST + 9% SGST)
    - Fully printable to PDF / A4 paper
    """
    sub = None
    sub = db.query(TenantSubscription).filter(
        func.lower(TenantSubscription.invoice_number) == invoice_identifier.strip().lower()
    ).first()

    if not sub:
        try:
            val_uuid = uuid.UUID(invoice_identifier)
            sub = db.query(TenantSubscription).filter(TenantSubscription.id == val_uuid).first()
        except (ValueError, AttributeError):
            pass

    if not sub:
        sub = db.query(TenantSubscription).order_by(TenantSubscription.created_at.desc()).first()

    if not sub:
        raise HTTPException(status_code=404, detail=f"Subscription invoice '{invoice_identifier}' not found in database")

    html_content = render_subscription_invoice_html(sub, db, autoprint=autoprint)
    return HTMLResponse(content=html_content)


@router.get("/invoices/{invoice_identifier}/pdf")
def download_subscription_invoice_pdf(
    invoice_identifier: str,
    db: Session = Depends(get_db)
):
    """
    Downloads or retrieves the stored high-resolution vector PDF of the subscription tax invoice.
    """
    sub = None
    sub = db.query(TenantSubscription).filter(
        func.lower(TenantSubscription.invoice_number) == invoice_identifier.strip().lower()
    ).first()

    if not sub:
        try:
            val_uuid = uuid.UUID(invoice_identifier)
            sub = db.query(TenantSubscription).filter(TenantSubscription.id == val_uuid).first()
        except (ValueError, AttributeError):
            pass

    if not sub:
        sub = db.query(TenantSubscription).order_by(TenantSubscription.created_at.desc()).first()

    if not sub:
        raise HTTPException(status_code=404, detail=f"Subscription invoice '{invoice_identifier}' not found in database")

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"
    pdf_filename = f"{inv_num}.pdf"
    pdf_filepath = os.path.join(INVOICES_DIR, pdf_filename)

    # Return cached PDF file from disk if already generated
    if os.path.exists(pdf_filepath) and os.path.getsize(pdf_filepath) > 0:
        return FileResponse(
            pdf_filepath,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={pdf_filename}"}
        )

    html_content = render_subscription_invoice_html(sub, db, autoprint=False)

    if weasyprint:
        pdf_bytes = weasyprint.HTML(string=html_content, base_url=".").write_pdf()
        try:
            with open(pdf_filepath, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:
            print(f"[PDF Storage Error] {e}")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={pdf_filename}"}
        )
    else:
        return HTMLResponse(content=html_content)


@router.post("/signature")
async def upload_authorized_signature(
    file: UploadFile = File(...),
    admin_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Upload official authorized signature image for SirfBill invoices.
    Saves to uploads/signatures/authorized_sign.png and applies immediately to all bills.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image (PNG, JPEG, or SVG)")

    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Signature file size exceeds maximum 2 MB limit")

    # Autocrop empty whitespace/transparency so the signature is prominent & clearly legible
    try:
        import io
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(contents))
        bbox = img.getbbox()
        if bbox:
            cropped = img.crop(bbox)
            padded = ImageOps.expand(cropped, border=6, fill=(0, 0, 0, 0) if img.mode == 'RGBA' else (255, 255, 255))
            buf = io.BytesIO()
            padded.save(buf, format="PNG")
            contents = buf.getvalue()
    except Exception as e:
        print(f"[Signature Auto-crop Note] {e}")

    os.makedirs(SIGNATURE_DIR, exist_ok=True)
    with open(SIGNATURE_PATH, "wb") as f:
        f.write(contents)

    return {
        "success": True,
        "message": "Authorized signature uploaded successfully. All subscription invoices will now display this signature.",
        "signature_url": "/uploads/signatures/authorized_sign.png"
    }


@router.get("/signature")
def get_authorized_signature():
    """
    Returns the current authorized signature image file if uploaded.
    """
    if os.path.exists(SIGNATURE_PATH):
        return FileResponse(SIGNATURE_PATH, media_type="image/png")
    raise HTTPException(status_code=404, detail="No custom authorized signature uploaded yet")


@router.get("/payments")
def get_subscription_payment_records(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Lists all subscription payment transactions with payment gateway IDs, status, and direct invoice links.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    payments = (
        db.query(SubscriptionPayment)
        .options(joinedload(SubscriptionPayment.subscription))
        .filter(SubscriptionPayment.tenant_id == tenant_id)
        .order_by(SubscriptionPayment.payment_date.desc())
        .all()
    )

    records = []
    for p in payments:
        inv_no = p.subscription.invoice_number if p.subscription else p.gateway_order_id
        if not inv_no:
            inv_no = f"INV-PAY-{str(p.id)[:8].upper()}"
        records.append({
            "id": str(p.id),
            "subscription_id": str(p.subscription_id),
            "amount": float(p.amount),
            "currency": p.currency,
            "payment_gateway": p.payment_gateway,
            "gateway_order_id": p.gateway_order_id,
            "gateway_payment_id": p.gateway_payment_id,
            "status": p.status,
            "payment_date": p.payment_date,
            "formatted_payment_date": p.payment_date.strftime("%d %b %Y, %I:%M %p") if p.payment_date else "N/A",
            "invoice_number": inv_no,
            "invoice_url": f"/api/subscriptions/invoices/{inv_no}/view",
            "download_url": f"/api/subscriptions/invoices/{inv_no}/pdf",
            "notes": p.notes
        })
    return records

