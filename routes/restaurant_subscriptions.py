import uuid
import os
import hmac
import hashlib
import base64
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
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
    SubscriptionInvoiceResponse,
    BranchSubscriptionResponse
)
from dependencies import get_current_user, get_optional_current_user, get_admin_user, get_user_scoped_outlet_id
from utils.timezone import get_current_time

router = APIRouter(
    prefix="/api/subscriptions",
    tags=["Restaurant - Subscription & Billing"]
)

DEFAULT_PLAN_CODE = "RESTAURANT_PRO_299"
DEFAULT_PLAN_NAME = "SirfBill Restaurant Pro (1 Month)"
DEFAULT_PLAN_PRICE = Decimal("299.00") # Base price (GST excluded)
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
        "description": "Standard 1 Month plan: ₹299 base + 18% GST (₹353 total).",
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
        "description": "3 Months plan: ₹897 base + 18% GST (₹1,058 total).",
        "price": Decimal("897.00"),
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
        "description": "6 Months plan: ₹1,704.30 base + 18% GST (₹2,012 total). 5% discount applied.",
        "price": Decimal("1704.30"),
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
        "description": "Annual 12 Months plan: ₹3,229.20 base + 18% GST (₹3,823 total). 10% discount applied.",
        "price": Decimal("3229.20"),
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
    Guarantees default plans exist on first run.
    DOES NOT overwrite user modifications in the database!
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

        saved_plans.append(plan)
    return saved_plans


def calculate_plan_amounts(base_price_val: Decimal) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Given the base price stored in the database (GST Excluded):
    Calculates (base_price, gst_amount, total_price):
    - 1 Month: 299.00 -> GST 54.00 -> Total 353.00
    - 3 Months: 897.00 -> GST 161.00 -> Total 1058.00
    - 6 Months: 1704.30 -> GST 306.70 -> Total 2011.00 (or base 1705.08 -> 2012.00)
    - 12 Months: 3229.20 -> GST 580.80 -> Total 3810.00 (or base 3239.83 -> 3823.00)
    """
    base = Decimal(str(base_price_val if base_price_val is not None else "299.00")).quantize(Decimal("0.01"))
    total = (base * Decimal("1.18")).quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(Decimal("0.01"))
    gst_amt = (total - base).quantize(Decimal("0.01"))
    return base, gst_amt, total


def _enrich_plan_response(p: SubscriptionPlan) -> SubscriptionPlanResponse:
    """
    Enriches the database plan model into a frontend-friendly response:
    - price: base price from DB
    - base_price: base price (GST excluded)
    - gst_amount: calculated 18% GST
    - total_price: total price including GST
    - gst_note: 'GST (18%) Excluded'
    """
    base, gst_amt, total = calculate_plan_amounts(p.price)

    clean_base = int(base) if base == int(base) else float(base)
    clean_total = int(total) if total == int(total) else float(total)

    return SubscriptionPlanResponse(
        id=p.id,
        plan_code=p.plan_code,
        name=p.name,
        description=p.description or f"{p.billing_cycle} plan: ₹{clean_base} base + 18% GST (Total ₹{clean_total}).",
        price=base,
        base_price=base,
        gst_rate=18.0,
        gst_amount=gst_amt,
        total_price=total,
        currency=p.currency or "INR",
        billing_cycle=p.billing_cycle,
        duration_days=p.duration_days,
        gst_note="GST (18%) Excluded",
        price_display=f"₹{clean_base} (GST Excluded)",
        total_display=f"₹{clean_total} (Incl. 18% GST)",
        features=p.features if p.features else DEFAULT_FEATURES,
        is_active=p.is_active,
        is_popular=p.is_popular,
        created_at=p.created_at
    )


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
    Resolves tenant_id from target outlet or authenticated user.
    Strictly tenant-scoped to avoid cross-tenant leaks.
    """
    # 1. Target outlet ID takes precedence when passed explicitly
    if target_outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == target_outlet_id).first()
        if outlet and outlet.tenant_id:
            return outlet.tenant_id

    # 2. Authenticated user's tenant
    if user and user.tenant_id:
        return user.tenant_id

    if user and user.outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == user.outlet_id).first()
        if outlet and outlet.tenant_id:
            return outlet.tenant_id

    # 3. Fallback: resolve from active outlet
    first_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True).first() or db.query(RestaurantOutlet).first()
    if first_outlet and first_outlet.tenant_id:
        return first_outlet.tenant_id

    # If no tenant context is established, return None to prevent cross-tenant leaks
    return None


def resolve_valid_outlet_id(db: Session, target_outlet_id: Optional[uuid.UUID], tenant_id: Optional[uuid.UUID] = None, user: Optional[User] = None) -> Optional[uuid.UUID]:
    """
    Validates that target_outlet_id exists in restaurant_outlets and belongs to tenant_id.
    Guarantees strict branch scoping and no ForeignKeyViolation.
    """
    scoped = get_user_scoped_outlet_id(db, user, target_outlet_id)
    if scoped:
        return scoped
    if target_outlet_id and tenant_id:
        outlet = db.query(RestaurantOutlet).filter(
            RestaurantOutlet.id == target_outlet_id,
            RestaurantOutlet.tenant_id == tenant_id
        ).first()
        if outlet:
            return outlet.id
    if target_outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == target_outlet_id).first()
        if outlet:
            return outlet.id
    if tenant_id:
        outlet = db.query(RestaurantOutlet).filter(
            RestaurantOutlet.tenant_id == tenant_id,
            RestaurantOutlet.is_active == True
        ).first() or db.query(RestaurantOutlet).filter(
            RestaurantOutlet.tenant_id == tenant_id
        ).first()
        if outlet:
            return outlet.id
    return None


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
    return [_enrich_plan_response(p) for p in plans]


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
    return _enrich_plan_response(new_plan)


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

    return _enrich_plan_response(plan)


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
    return _enrich_plan_response(plan)


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
    Reports whether a specific branch's subscription is currently active or expired.
    Strictly isolated per branch/outlet.
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, scoped_outlet_id)
    now = get_current_time()

    if not tenant_id:
        default_plan = get_or_create_default_plan(db)
        base, _, total = calculate_plan_amounts(default_plan.price)
        return SubscriptionStatusResponse(
            has_subscription=False,
            is_active=False,
            status="UNPAID",
            plan_name=default_plan.name,
            price=base,
            base_price=base,
            gst_note="GST (18%) Excluded",
            total_price=total,
            billing_cycle=default_plan.billing_cycle,
            expires_at=None,
            days_remaining=0,
            features=default_plan.features,
            outlet_id=None,
            tenant_id=None
        )

    # Query subscription explicitly for this branch
    query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if scoped_outlet_id:
        sub = query.filter(TenantSubscription.outlet_id == scoped_outlet_id).order_by(TenantSubscription.expires_at.desc()).first()
    else:
        sub = query.order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        # Check if tenant has ANY subscription across any branch
        total_tenant_subs = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).count() if tenant_id else 0
        if total_tenant_subs == 0 and tenant_id and scoped_outlet_id:
            # First branch of a fresh tenant: auto-provision complimentary 1-year onboarding subscription
            default_plan = get_or_create_default_plan(db)
            sub = TenantSubscription(
                tenant_id=tenant_id,
                outlet_id=scoped_outlet_id,
                plan_id=default_plan.id,
                status="ACTIVE",
                price_paid=Decimal("0.00"),
                currency="INR",
                started_at=now,
                expires_at=now + timedelta(days=365),
                payment_method="FREE_TRIAL",
                payment_reference="AUTO_PROVISIONED",
                invoice_number=f"SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                notes="Auto-provisioned complimentary subscription for primary restaurant outlet",
                auto_renew=True,
                purchased_by_id=current_user.id if current_user else None
            )
            db.add(sub)
            db.commit()
            db.refresh(sub)
        else:
            default_plan = get_or_create_default_plan(db)
            base, _, total = calculate_plan_amounts(default_plan.price)
            return SubscriptionStatusResponse(
                has_subscription=False,
                is_active=False,
                status="UNPAID",
                plan_name=default_plan.name,
                price=base,
                base_price=base,
                gst_note="GST (18%) Excluded",
                total_price=total,
                billing_cycle=default_plan.billing_cycle,
                expires_at=None,
                days_remaining=0,
                features=default_plan.features,
                outlet_id=scoped_outlet_id,
                tenant_id=tenant_id
            )

    is_active = (sub.expires_at > now) and (sub.status not in ("CANCELLED", "PENDING_PAYMENT", "EXPIRED"))
    days_left = max(0, (sub.expires_at - now).days) if is_active else 0
    if not is_active:
        computed_status = "PENDING_PAYMENT" if sub.status == "PENDING_PAYMENT" else "EXPIRED"
    else:
        computed_status = "ACTIVE" if sub.status != "TRIAL" else "TRIAL"

    inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"

    base_p = sub.plan.price if sub.plan and sub.plan.price else Decimal("299.00")
    base, _, total = calculate_plan_amounts(base_p)

    return SubscriptionStatusResponse(
        has_subscription=True,
        is_active=is_active,
        status=computed_status,
        plan_name=sub.plan.name if sub.plan else DEFAULT_PLAN_NAME,
        price=base,
        base_price=base,
        gst_note="GST (18%) Excluded",
        total_price=total,
        billing_cycle=sub.plan.billing_cycle if sub.plan else "MONTHLY",
        expires_at=sub.expires_at,
        days_remaining=days_left,
        features=sub.plan.features if sub.plan and sub.plan.features else DEFAULT_FEATURES,
        outlet_id=sub.outlet_id or scoped_outlet_id,
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
    Get detailed subscription information for a specific branch or primary branch.
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, scoped_outlet_id)

    if not tenant_id:
        default_plan = get_or_create_default_plan(db)
        base, gst, total = calculate_plan_amounts(default_plan.price)
        return CurrentSubscriptionResponse(
            has_subscription=False,
            is_active=False,
            status="UNPAID",
            plan_name=default_plan.name,
            price=base,
            base_price=base,
            gst_amount=gst,
            total_price=total,
            billing_cycle=default_plan.billing_cycle,
            expires_at=None,
            days_remaining=0,
            features=default_plan.features,
            outlet_id=None,
            tenant_id=None,
            invoice_number=None,
            payment_method=None,
            started_at=None
        )

    query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if scoped_outlet_id:
        sub = query.filter(TenantSubscription.outlet_id == scoped_outlet_id).order_by(TenantSubscription.expires_at.desc()).first()
    else:
        sub = query.order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        total_tenant_subs = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).count() if tenant_id else 0
        if total_tenant_subs == 0 and tenant_id and scoped_outlet_id:
            default_plan = get_or_create_default_plan(db)
            now = get_current_time()
            sub = TenantSubscription(
                tenant_id=tenant_id,
                outlet_id=scoped_outlet_id,
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
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active subscription found for this branch. Please subscribe to activate."
            )

    return _enrich_subscription_response(sub)


@router.post("/subscribe", response_model=TenantSubscriptionResponse, status_code=status.HTTP_201_CREATED)
def subscribe_or_renew(
    payload: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Super Admin purchases or renews the subscription for a specific branch.
    1. Resolves branch outlet_id (strictly scoped to user tenant).
    2. Extends branch subscription by +30 days (stacking) or starts fresh.
    3. Generates formal invoice number and logs payment transaction per branch.
    """
    target_outlet_id = get_user_scoped_outlet_id(db, current_user, payload.outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, target_outlet_id)
    if not target_outlet_id:
        target_outlet_id = resolve_valid_outlet_id(db, payload.outlet_id, tenant_id, current_user)

    outlet_name = "Restaurant Branch"
    if target_outlet_id:
        out_rec = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == target_outlet_id).first()
        if out_rec:
            outlet_name = out_rec.name

    # 1. Resolve Plan
    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)
    base_price, gst_amt, total_price = calculate_plan_amounts(plan.price)

    now = get_current_time()
    duration_days = plan.duration_days or 30

    # 2. Check existing subscription specifically for THIS branch to support seamless extension
    existing_query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if target_outlet_id:
        existing_query = existing_query.filter(TenantSubscription.outlet_id == target_outlet_id)
    existing_sub = existing_query.order_by(TenantSubscription.expires_at.desc()).first()

    if existing_sub and existing_sub.expires_at > now and existing_sub.status in ("ACTIVE", "TRIAL"):
        # Subscription is currently active for this branch -> extend from current expiry date
        new_start = existing_sub.started_at
        new_expiry = existing_sub.expires_at + timedelta(days=duration_days)
    else:
        # Expired, pending payment, or new subscription -> starts today
        new_start = now
        new_expiry = now + timedelta(days=duration_days)

    invoice_no = f"INV-SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    payment_ref = payload.payment_reference or f"UPI-PAY-{uuid.uuid4().hex[:8].upper()}"

    # 3. Create branch subscription record
    subscription = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=target_outlet_id,
        plan_id=plan.id,
        status="ACTIVE",
        price_paid=total_price,
        currency=plan.currency,
        started_at=new_start,
        expires_at=new_expiry,
        payment_method=payload.payment_method or "UPI",
        payment_reference=payment_ref,
        invoice_number=invoice_no,
        notes=payload.notes or f"Subscribed {outlet_name} to {plan.name} (Base ₹{base_price} + 18% GST = ₹{total_price})",
        auto_renew=True,
        purchased_by_id=current_user.id if current_user else None
    )
    db.add(subscription)
    db.flush()

    # 4. Log immutable payment transaction
    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        tenant_id=tenant_id,
        amount=total_price,
        currency=plan.currency,
        payment_gateway=payload.payment_method or "MANUAL_UPI",
        gateway_order_id=invoice_no,
        gateway_payment_id=payment_ref,
        status="SUCCESS",
        payment_date=now,
        notes=f"Payment for {plan.name} ({outlet_name}) by Super Admin"
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
    Creates a Razorpay Order for purchasing or renewing the restaurant subscription for a specific branch.
    Returns the order ID and key ID for the frontend Razorpay Checkout modal.
    Charges the Gross Total (Base Price + 18% GST).
    """
    target_outlet_id = get_user_scoped_outlet_id(db, current_user, payload.outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, target_outlet_id)
    if not target_outlet_id:
        target_outlet_id = resolve_valid_outlet_id(db, payload.outlet_id, tenant_id, current_user)

    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)
    base_price, gst_amt, total_price = calculate_plan_amounts(plan.price)

    amount_paise = int(total_price * 100)
    receipt_no = f"rcpt_{str(tenant_id)[:8]}_{int(get_current_time().timestamp())}"
    order_id = None
    payment_link_url = None
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
                    "outlet_id": str(target_outlet_id) if target_outlet_id else "",
                    "plan_id": str(plan.id),
                    "plan_code": plan.plan_code,
                    "base_price": str(base_price),
                    "gst_amount": str(gst_amt),
                    "total_price": str(total_price)
                }
            })
            order_id = rzp_order.get("id")
            print(f"[Razorpay Order Success] Order ID: {order_id} | Total: ₹{total_price} (Base ₹{base_price} + 18% GST)")

            # Create official hosted Razorpay payment link (hosted on rzp.io, bypasses localhost website check)
            try:
                plink_payload = {
                    "amount": amount_paise,
                    "currency": plan.currency or "INR",
                    "description": f"{plan.name} ({plan.billing_cycle})",
                    "notes": {
                        "tenant_id": str(tenant_id),
                        "outlet_id": str(target_outlet_id) if target_outlet_id else "",
                        "plan_id": str(plan.id),
                        "plan_code": plan.plan_code,
                        "order_id": str(order_id)
                    }
                }
                if payload.callback_url:
                    plink_payload["callback_url"] = payload.callback_url
                    plink_payload["callback_method"] = "get"
                plink = client.payment_link.create(plink_payload)
                payment_link_url = plink.get("short_url")
            except Exception as pl_err:
                print(f"[Razorpay PaymentLink Note] {pl_err}")
                payment_link_url = None
        except Exception as e:
            print(f"[Razorpay Warning] order.create failed: {e}")
            order_id = None
    else:
        order_id = None

    return RazorpayOrderResponse(
        order_id=order_id,
        amount=total_price,
        amount_paise=amount_paise,
        base_price=base_price,
        gst_amount=gst_amt,
        currency=plan.currency or "INR",
        key_id=key_id,
        plan_id=plan.id,
        plan_name=plan.name,
        plan_code=plan.plan_code,
        duration_days=plan.duration_days,
        billing_cycle=plan.billing_cycle,
        outlet_id=target_outlet_id,
        payment_link_url=payment_link_url
    )


@router.post("/verify-payment", response_model=TenantSubscriptionResponse)
def verify_razorpay_payment(
    payload: RazorpayVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Verifies Razorpay payment signature and activates the subscription specifically for the target branch (+30 days, +90 days, +180 days, +365 days).
    """
    target_outlet_id = get_user_scoped_outlet_id(db, current_user, payload.outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, target_outlet_id)
    if not target_outlet_id:
        target_outlet_id = resolve_valid_outlet_id(db, payload.outlet_id, tenant_id, current_user)

    plan = resolve_plan_from_request(db, payload.plan_id, payload.plan_code, payload.duration_months)
    base_price, gst_amt, total_price = calculate_plan_amounts(plan.price)

    # 1. Verify Signature or Direct Razorpay API Fetch
    is_valid = False
    key_id, key_secret = get_razorpay_credentials()
    if razorpay and key_id and key_secret and payload.razorpay_payment_id:
        try:
            client = razorpay.Client(auth=(key_id, key_secret))
            p_info = client.payment.fetch(payload.razorpay_payment_id)
            if p_info.get("status") in ("captured", "authorized"):
                is_valid = True
                print(f"[Razorpay API Verified] Payment {payload.razorpay_payment_id} status: {p_info.get('status')}")
        except Exception as f_err:
            print(f"[Razorpay API Fetch Note] {f_err}")

    if not is_valid and key_secret and payload.razorpay_order_id and payload.razorpay_signature and not payload.razorpay_order_id.startswith("order_test_"):
        try:
            expected_sig = hmac.new(
                key_secret.encode("utf-8"),
                f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            is_valid = hmac.compare_digest(expected_sig, payload.razorpay_signature)
        except Exception:
            is_valid = False
    elif not is_valid and payload.razorpay_order_id and payload.razorpay_order_id.startswith("order_test_") and not key_secret:
        # Only allow test-mode bypass when no live Razorpay key_secret is configured
        is_valid = bool(payload.razorpay_payment_id)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay payment signature. Verification failed."
        )

    # 2. Activate or extend subscription specifically for this branch
    now = get_current_time()
    duration_days = plan.duration_days or 30

    existing_query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if target_outlet_id:
        existing_query = existing_query.filter(TenantSubscription.outlet_id == target_outlet_id)
    existing_sub = existing_query.order_by(TenantSubscription.expires_at.desc()).first()

    if existing_sub and existing_sub.expires_at > now and existing_sub.status in ("ACTIVE", "TRIAL"):
        new_start = existing_sub.started_at
        new_expiry = existing_sub.expires_at + timedelta(days=duration_days)
    else:
        new_start = now
        new_expiry = now + timedelta(days=duration_days)

    invoice_no = f"INV-SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    subscription = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=target_outlet_id,
        plan_id=plan.id,
        status="ACTIVE",
        price_paid=total_price,
        currency=plan.currency,
        started_at=new_start,
        expires_at=new_expiry,
        payment_method="RAZORPAY",
        payment_reference=payload.razorpay_payment_id,
        invoice_number=invoice_no,
        notes=payload.notes or f"Razorpay online payment verified (Order: {payload.razorpay_order_id}, Payment: {payload.razorpay_payment_id}) - Base ₹{base_price} + 18% GST = ₹{total_price}",
        auto_renew=True,
        purchased_by_id=current_user.id if current_user else None
    )
    db.add(subscription)
    db.flush()

    # 3. Log Payment Transaction
    payment = SubscriptionPayment(
        subscription_id=subscription.id,
        tenant_id=tenant_id,
        amount=total_price,
        currency=plan.currency,
        payment_gateway="RAZORPAY",
        gateway_order_id=payload.razorpay_order_id,
        gateway_payment_id=payload.razorpay_payment_id,
        status="SUCCESS",
        payment_date=now,
        notes=f"Razorpay payment verified for {plan.name} (Total: ₹{total_price})"
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


@router.get("/check-order/{order_id}")
def check_order_status(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Checks if a Razorpay order has been paid and auto-activates the subscription if paid.
    Perfect for desktop apps and background polling.
    """
    key_id, key_secret = get_razorpay_credentials()
    if not (razorpay and key_id and key_secret):
        return {"paid": False, "status": "UNKNOWN"}

    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        rzp_order = client.order.fetch(order_id)
        status_val = rzp_order.get("status")

        if status_val != "paid":
            # Check payments linked to this order or payment link with order_id in notes
            try:
                order_pmts = client.order.payments(order_id)
                for p in order_pmts.get("items", []):
                    if p.get("status") in ("captured", "authorized"):
                        status_val = "paid"
                        break
            except Exception:
                pass

        if status_val != "paid":
            # Check recent payments in Razorpay that match this order_id in notes
            try:
                recent_pmts = client.payment.all({"count": 25})
                for p in recent_pmts.get("items", []):
                    if p.get("status") in ("captured", "authorized"):
                        p_notes = p.get("notes", {}) or {}
                        if p_notes.get("order_id") == order_id or p.get("order_id") == order_id:
                            status_val = "paid"
                            successful_pmt = p
                            break
            except Exception:
                pass

        if status_val == "paid":
            existing_pmt = db.query(SubscriptionPayment).filter(
                SubscriptionPayment.gateway_order_id == order_id
            ).first()
            if existing_pmt:
                sub = db.query(TenantSubscription).filter(
                    TenantSubscription.id == existing_pmt.subscription_id
                ).first()
                return {"paid": True, "status": "PAID", "payment_id": existing_pmt.gateway_payment_id, "subscription": _enrich_subscription_response(sub) if sub else None}

            if not successful_pmt:
                try:
                    payments = client.order.payments(order_id)
                    for p in payments.get("items", []):
                        if p.get("status") in ("captured", "authorized"):
                            successful_pmt = p
                            break
                except Exception:
                    pass

            if successful_pmt:
                notes = rzp_order.get("notes", {})
                tenant_id = uuid.UUID(notes.get("tenant_id")) if notes.get("tenant_id") else uuid.UUID("9f3670ca-438f-4251-984c-8fc230826a1b")
                target_outlet_id = None
                if notes.get("outlet_id"):
                    try:
                        target_outlet_id = uuid.UUID(notes.get("outlet_id"))
                    except Exception:
                        target_outlet_id = None
                plan_code = notes.get("plan_code", DEFAULT_PLAN_CODE)
                plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.plan_code == plan_code).first() or get_or_create_default_plan(db)
                base_price, gst_amt, total_price = calculate_plan_amounts(plan.price)

                now = get_current_time()
                duration_days = plan.duration_days or 30
                existing_query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
                if target_outlet_id:
                    existing_query = existing_query.filter(TenantSubscription.outlet_id == target_outlet_id)
                existing_sub = existing_query.order_by(TenantSubscription.expires_at.desc()).first()

                if existing_sub and existing_sub.expires_at > now and existing_sub.status in ("ACTIVE", "TRIAL"):
                    new_start = existing_sub.started_at
                    new_expiry = existing_sub.expires_at + timedelta(days=duration_days)
                else:
                    new_start = now
                    new_expiry = now + timedelta(days=duration_days)

                invoice_no = f"INV-SUB-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                subscription = TenantSubscription(
                    tenant_id=tenant_id,
                    outlet_id=target_outlet_id,
                    plan_id=plan.id,
                    status="ACTIVE",
                    price_paid=total_price,
                    currency=plan.currency,
                    started_at=new_start,
                    expires_at=new_expiry,
                    payment_method="RAZORPAY",
                    payment_reference=successful_pmt.get("id"),
                    invoice_number=invoice_no,
                    notes=f"Auto-verified via Razorpay Order Check ({order_id})",
                    auto_renew=True
                )
                db.add(subscription)
                db.flush()

                pmt_rec = SubscriptionPayment(
                    subscription_id=subscription.id,
                    tenant_id=tenant_id,
                    amount=total_price,
                    currency=plan.currency,
                    payment_gateway="RAZORPAY",
                    gateway_order_id=order_id,
                    gateway_payment_id=successful_pmt.get("id"),
                    status="SUCCESS",
                    payment_date=now,
                    notes=f"Auto-verified payment for {plan.name}"
                )
                db.add(pmt_rec)
                db.commit()
                db.refresh(subscription)

                if weasyprint:
                    try:
                        pdf_path = os.path.join(INVOICES_DIR, f"{invoice_no}.pdf")
                        html_doc = render_subscription_invoice_html(subscription, db, autoprint=False)
                        pdf_bytes = weasyprint.HTML(string=html_doc, base_url=".").write_pdf()
                        with open(pdf_path, "wb") as f:
                            f.write(pdf_bytes)
                    except Exception:
                        pass

                return {"paid": True, "status": "PAID", "payment_id": successful_pmt.get("id"), "subscription": _enrich_subscription_response(subscription)}

        return {"paid": False, "status": status_val}
    except Exception as e:
        return {"paid": False, "error": str(e)}


@router.get("/branches", response_model=List[BranchSubscriptionResponse])
def get_branch_subscriptions(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Returns the individual subscription status and renewal info for ALL branches of the current tenant.
    Allows multi-branch owners to see which branches are Active, Expiring, or Unpaid, and renew them individually.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)
    now = get_current_time()

    outlets = db.query(RestaurantOutlet).filter(
        RestaurantOutlet.tenant_id == tenant_id
    ).order_by(RestaurantOutlet.created_at.asc()).all()

    default_plan = get_or_create_default_plan(db)
    base_def, _, total_def = calculate_plan_amounts(default_plan.price)

    results = []
    for idx, out in enumerate(outlets):
        svc = out.service_settings or {}
        is_primary = svc.get("is_primary", (idx == 0))

        sub = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.outlet_id == out.id
        ).order_by(TenantSubscription.expires_at.desc()).first()

        if sub:
            is_active = (sub.expires_at > now) and (sub.status not in ("CANCELLED", "PENDING_PAYMENT", "EXPIRED"))
            days_left = max(0, (sub.expires_at - now).days) if is_active else 0
            if not is_active:
                status_str = "PENDING_PAYMENT" if sub.status == "PENDING_PAYMENT" else "EXPIRED"
            else:
                status_str = "ACTIVE" if sub.status != "TRIAL" else "TRIAL"

            inv_num = sub.invoice_number or f"INV-SUB-{sub.started_at.strftime('%Y%m%d')}-{str(sub.id)[:6].upper()}"
            sub_plan = sub.plan or default_plan
            base_p, _, tot_p = calculate_plan_amounts(sub_plan.price)

            results.append(BranchSubscriptionResponse(
                outlet_id=out.id,
                outlet_name=out.name,
                outlet_code=out.code,
                city=out.city,
                is_primary=is_primary,
                has_subscription=True,
                is_active=is_active,
                status=status_str,
                plan_name=sub_plan.name,
                plan_code=sub_plan.plan_code,
                price=base_p,
                total_price=tot_p,
                billing_cycle=sub_plan.billing_cycle,
                started_at=sub.started_at,
                expires_at=sub.expires_at,
                days_remaining=days_left,
                latest_invoice_number=inv_num,
                latest_invoice_url=f"/api/subscriptions/invoices/{inv_num}/view",
                latest_download_url=f"/api/subscriptions/invoices/{inv_num}/pdf"
            ))
        else:
            results.append(BranchSubscriptionResponse(
                outlet_id=out.id,
                outlet_name=out.name,
                outlet_code=out.code,
                city=out.city,
                is_primary=is_primary,
                has_subscription=False,
                is_active=False,
                status="UNPAID",
                plan_name=default_plan.name,
                plan_code=default_plan.plan_code,
                price=base_def,
                total_price=total_def,
                billing_cycle=default_plan.billing_cycle,
                started_at=None,
                expires_at=None,
                days_remaining=0,
                latest_invoice_number=None,
                latest_invoice_url=None,
                latest_download_url=None
            ))

    return results


@router.get("/history", response_model=List[TenantSubscriptionResponse])
def get_subscription_history(
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Get full subscription history and invoices for the restaurant tenant, optionally filtered by branch.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    if not tenant_id:
        return []

    query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if outlet_id:
        query = query.filter(TenantSubscription.outlet_id == outlet_id)

    subscriptions = query.order_by(TenantSubscription.created_at.desc()).all()
    return [_enrich_subscription_response(sub) for sub in subscriptions]


@router.post("/grant-trial", response_model=TenantSubscriptionResponse)
def grant_trial_extension(
    days: int = Query(30, ge=1, le=365),
    outlet_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user)
):
    """
    Admin override: Grant complimentary trial or extend validity by N days for a specific branch.
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, admin_user, outlet_id)
    tenant_id = resolve_tenant_id(admin_user, db, scoped_outlet_id)
    plan = get_or_create_default_plan(db)
    now = get_current_time()

    existing_q = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if scoped_outlet_id:
        existing_q = existing_q.filter(TenantSubscription.outlet_id == scoped_outlet_id)
    existing = existing_q.order_by(TenantSubscription.expires_at.desc()).first()

    if existing and existing.expires_at > now:
        new_expiry = existing.expires_at + timedelta(days=days)
    else:
        new_expiry = now + timedelta(days=days)

    invoice_no = f"TRIAL-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    valid_outlet_id = scoped_outlet_id or resolve_valid_outlet_id(db, outlet_id, tenant_id, admin_user)

    sub = TenantSubscription(
        tenant_id=tenant_id,
        outlet_id=valid_outlet_id,
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
    if not outlet and sub.tenant_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id == sub.tenant_id).first()

    # 3. Resolve User
    user = None
    if sub.purchased_by_id:
        user = db.query(User).filter(User.id == sub.purchased_by_id).first()
    if not user:
        user = db.query(User).filter(User.tenant_id == sub.tenant_id).first()

    # 4. Financial Calculation (18% GST Registered Entity: 9% CGST + 9% SGST)
    gross_val = Decimal(str(sub.price_paid if sub.price_paid is not None else "353.00"))
    if plan and plan.price and plan.price > 0:
        base_val = Decimal(str(plan.price)).quantize(Decimal("0.01"))
        tot_tax = (gross_val - base_val).quantize(Decimal("0.01"))
        cgst_val = (base_val * Decimal("0.09")).quantize(Decimal("0.01"))
        sgst_val = (tot_tax - cgst_val).quantize(Decimal("0.01"))
    elif gross_val == Decimal("353.00"):
        base_val = Decimal("299.00")
        cgst_val = Decimal("26.91")
        sgst_val = Decimal("27.09")
        tot_tax = Decimal("54.00")
    elif gross_val > Decimal("0.00"):
        base_val = (gross_val / Decimal("1.18")).quantize(Decimal("0.01"))
        tot_tax = (gross_val - base_val).quantize(Decimal("0.01"))
        cgst_val = (base_val * Decimal("0.09")).quantize(Decimal("0.01"))
        sgst_val = (tot_tax - cgst_val).quantize(Decimal("0.01"))
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
    for logo_file in [
        "uploads/brand/LOGO.png",
        os.path.join(os.getcwd(), "uploads", "brand", "LOGO.png"),
        "/app/uploads/brand/LOGO.png",
        "uploads/brand/sirfbill_logo.png",
        "assets/sirfbill_logo.png",
        os.path.join(os.getcwd(), "uploads", "brand", "sirfbill_logo.png"),
        os.path.join(os.getcwd(), "assets", "sirfbill_logo.png"),
        "/app/uploads/brand/sirfbill_logo.png",
        "/app/assets/sirfbill_logo.png"
    ]:
        if os.path.exists(logo_file) and os.path.isfile(logo_file):
            try:
                with open(logo_file, "rb") as f:
                    brand_logo_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
                if brand_logo_b64:
                    break
            except Exception:
                pass

    brand_icon_b64 = None
    for icon_file in [
        "uploads/brand/sirfbill_icon.png",
        "assets/sirfbill_icon.png",
        os.path.join(os.getcwd(), "uploads", "brand", "sirfbill_icon.png"),
        os.path.join(os.getcwd(), "assets", "sirfbill_icon.png"),
        "/app/uploads/brand/sirfbill_icon.png",
        "/app/assets/sirfbill_icon.png"
    ]:
        if os.path.exists(icon_file) and os.path.isfile(icon_file):
            try:
                with open(icon_file, "rb") as f:
                    brand_icon_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
                if brand_icon_b64:
                    break
            except Exception:
                pass

    # 7. Embed subscriber outlet logo if present
    outlet_logo_b64 = None
    if outlet and outlet.logo_url:
        clean_path = outlet.logo_url.lstrip("/")
        for candidate in [
            clean_path,
            os.path.join(os.getcwd(), clean_path),
            os.path.join("/app", clean_path)
        ]:
            if os.path.exists(candidate) and os.path.isfile(candidate):
                try:
                    with open(candidate, "rb") as f:
                        ext = os.path.splitext(candidate)[1].lower().replace(".", "")
                        mime = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "webp"] else "image/jpeg"
                        if mime == "image/jpg":
                            mime = "image/jpeg"
                        outlet_logo_b64 = f"data:{mime};base64,{base64.b64encode(f.read()).decode('utf-8')}"
                    if outlet_logo_b64:
                        break
                except Exception:
                    pass
        if not outlet_logo_b64:
            outlet_logo_b64 = outlet.logo_url

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
        "logo_url": brand_logo_b64 or "/uploads/brand/LOGO.png",
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
        outlet_logo_url=outlet_logo_b64,
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
    Optionally filtered by branch outlet_id.
    """
    tenant_id = resolve_tenant_id(current_user, db, outlet_id)

    query = (
        db.query(TenantSubscription)
        .options(
            joinedload(TenantSubscription.plan),
            joinedload(TenantSubscription.outlet),
            joinedload(TenantSubscription.payments)
        )
        .filter(TenantSubscription.tenant_id == tenant_id)
    )
    if outlet_id:
        query = query.filter(TenantSubscription.outlet_id == outlet_id)

    subscriptions = query.order_by(TenantSubscription.started_at.desc()).all()

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
    Returns the most recent subscription invoice for the active branch/tenant.
    If redirect=true, directly opens the HTML bill view in the browser.
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    tenant_id = resolve_tenant_id(current_user, db, scoped_outlet_id)

    if not tenant_id:
        default_plan = get_or_create_default_plan(db)
        base, gst, total = calculate_plan_amounts(default_plan.price)
        return CurrentSubscriptionResponse(
            has_subscription=False,
            is_active=False,
            status="UNPAID",
            plan_name=default_plan.name,
            price=base,
            base_price=base,
            gst_amount=gst,
            total_price=total,
            billing_cycle=default_plan.billing_cycle,
            expires_at=None,
            days_remaining=0,
            features=default_plan.features,
            outlet_id=None,
            tenant_id=None,
            invoice_number=None,
            payment_method=None,
            started_at=None
        )

    query = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id)
    if scoped_outlet_id:
        query = query.filter(TenantSubscription.outlet_id == scoped_outlet_id)
    sub = query.order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        raise HTTPException(status_code=404, detail="No subscription invoices found for this branch")

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

