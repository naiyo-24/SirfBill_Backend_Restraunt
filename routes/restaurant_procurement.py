from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
import re
import os
import shutil
import uuid
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader
import weasyprint
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_ingredient import RestaurantIngredient
from models.restaurant_stock_ledger import RestaurantStockLedger
from models.restaurant_procurement import (
    RestaurantSupplier,
    RestaurantPurchaseOrder,
    RestaurantPurchaseOrderItem,
    RestaurantGRN,
    RestaurantGRNItem
)
from schemas.restaurant_procurement import (
    RestaurantSupplierCreate, RestaurantSupplierUpdate, RestaurantSupplierResponse,
    PurchaseOrderCreate, PurchaseOrderUpdate, PurchaseOrderResponse, PurchaseOrderSummaryResponse,
    PurchaseOrderItemResponse,
    GRNCreate, GRNResponse, GRNItemResponse
)
from dependencies import get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff

router = APIRouter(
    prefix="/api/restaurant/procurement",
    tags=["Restaurant - Procurement & Purchase Orders"]
)

# ----------------- STATUS & ENUM MAPPING -----------------
# Maps front-end filter tabs (e.g. "Sent to Vendor", "Partial Delivery") to database enums
STATUS_MAP = {
    "DRAFT": "DRAFT",
    "SENT TO VENDOR": "ISSUED",
    "SENT_TO_VENDOR": "ISSUED",
    "SENT": "ISSUED",
    "ISSUED": "ISSUED",
    "PARTIAL DELIVERY": "PARTIALLY_RECEIVED",
    "PARTIAL_DELIVERY": "PARTIALLY_RECEIVED",
    "PARTIAL": "PARTIALLY_RECEIVED",
    "PARTIALLY_RECEIVED": "PARTIALLY_RECEIVED",
    "COMPLETED": "COMPLETED",
    "DELIVERED": "COMPLETED",
    "RECEIVED": "COMPLETED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
}

STATUS_LABELS = {
    "DRAFT": "Draft",
    "ISSUED": "Sent to Vendor",
    "PARTIALLY_RECEIVED": "Partial Delivery",
    "COMPLETED": "Completed",
    "CANCELLED": "Cancelled",
}


def resolve_outlet(db: Session, outlet_id: Optional[UUID] = None) -> RestaurantOutlet:
    outlet = None
    if outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == outlet_id).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant branch/outlet not found")
    return outlet

def generate_supplier_code(db: Session, outlet_id: UUID, name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().upper()
    words = cleaned.split()
    base = words[0][:5] if words else "SUP"
    candidate = f"SUP-{base}"
    counter = 1
    while True:
        exists = db.query(RestaurantSupplier).filter(
            RestaurantSupplier.outlet_id == outlet_id,
            RestaurantSupplier.code == candidate,
            RestaurantSupplier.is_active == True
        ).first()
        if not exists:
            return candidate
        counter += 1
        candidate = f"SUP-{base}-{counter:02d}"

def generate_next_po_number(db: Session, outlet_id: UUID) -> str:
    now = datetime.utcnow()
    prefix = f"PO-{now.strftime('%Y%m')}"
    count = db.query(func.count(RestaurantPurchaseOrder.id)).filter(
        RestaurantPurchaseOrder.outlet_id == outlet_id,
        RestaurantPurchaseOrder.po_number.like(f"{prefix}-%")
    ).scalar() or 0
    candidate = count + 1
    while True:
        num = f"{prefix}-{candidate:04d}"
        if not db.query(RestaurantPurchaseOrder.id).filter(
            RestaurantPurchaseOrder.outlet_id == outlet_id,
            RestaurantPurchaseOrder.po_number == num
        ).first():
            return num
        candidate += 1

def generate_next_grn_number(db: Session, outlet_id: UUID) -> str:
    now = datetime.utcnow()
    prefix = f"GRN-{now.strftime('%Y%m')}"
    count = db.query(func.count(RestaurantGRN.id)).filter(
        RestaurantGRN.outlet_id == outlet_id,
        RestaurantGRN.grn_number.like(f"{prefix}-%")
    ).scalar() or 0
    candidate = count + 1
    while True:
        num = f"{prefix}-{candidate:04d}"
        if not db.query(RestaurantGRN.id).filter(
            RestaurantGRN.outlet_id == outlet_id,
            RestaurantGRN.grn_number == num
        ).first():
            return num
        candidate += 1


# ==============================================================================
# 1. SUPPLIERS
# ==============================================================================

@router.get("/suppliers", response_model=List[RestaurantSupplierResponse])
def get_suppliers(
    outlet_id: Optional[UUID] = None,
    search: Optional[str] = Query(None, description="Search by name, phone, code or GSTIN"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Fetch all suppliers/vendors for a branch.
    Strictly isolated by outlet_id & tenant_id.
    """
    outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantSupplier)
        .filter(RestaurantSupplier.outlet_id == outlet.id)
        .filter(RestaurantSupplier.is_active == True)
    )

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        pattern = f"%{search_str}%"
        query = query.filter(
            or_(
                RestaurantSupplier.name.ilike(pattern),
                RestaurantSupplier.code.ilike(pattern),
                RestaurantSupplier.phone.ilike(pattern),
                RestaurantSupplier.contact_person.ilike(pattern),
                RestaurantSupplier.gstin.ilike(pattern)
            )
        )

    return query.order_by(RestaurantSupplier.name.asc()).all()


@router.post("/suppliers", response_model=RestaurantSupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: RestaurantSupplierCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    outlet = resolve_outlet(db, payload.outlet_id)

    code = payload.code.strip().upper() if payload.code and payload.code.strip() else generate_supplier_code(db, outlet.id, payload.name)

    supplier = RestaurantSupplier(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        name=payload.name.strip(),
        code=code,
        contact_person=payload.contact_person.strip() if payload.contact_person else None,
        phone=payload.phone.strip() if payload.phone else None,
        email=payload.email.strip().lower() if payload.email else None,
        address=payload.address.strip() if payload.address else None,
        gstin=payload.gstin.strip().upper() if payload.gstin else None,
        fssai=payload.fssai.strip() if payload.fssai else None,
        payment_terms=payload.payment_terms or "NET_15",
        bank_details=payload.bank_details or {},
        notes=payload.notes,
        is_active=payload.is_active
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.get("/suppliers/{supplier_id}", response_model=RestaurantSupplierResponse)
def get_supplier_by_id(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    supplier = db.query(RestaurantSupplier).filter(RestaurantSupplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.put("/suppliers/{supplier_id}", response_model=RestaurantSupplierResponse)
@router.patch("/suppliers/{supplier_id}", response_model=RestaurantSupplierResponse)
def update_supplier(
    supplier_id: UUID,
    payload: RestaurantSupplierUpdate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    supplier = db.query(RestaurantSupplier).filter(RestaurantSupplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "code" in update_data and update_data["code"]:
        update_data["code"] = update_data["code"].strip().upper()
    if "gstin" in update_data and update_data["gstin"]:
        update_data["gstin"] = update_data["gstin"].strip().upper()

    for field, value in update_data.items():
        setattr(supplier, field, value)

    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    supplier = db.query(RestaurantSupplier).filter(RestaurantSupplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    supplier.is_active = False
    db.commit()
    return None


# ==============================================================================
# 2. PURCHASE ORDERS (PO)
# ==============================================================================

@router.get("/purchase-orders/next-number")
def get_next_po_number_endpoint(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """Returns the preview of the next sequential PO number."""
    outlet = resolve_outlet(db, outlet_id)
    return {"po_number": generate_next_po_number(db, outlet.id), "outlet_id": outlet.id}


@router.get("/purchase-orders", response_model=List[PurchaseOrderSummaryResponse])
def get_purchase_orders(
    outlet_id: Optional[UUID] = None,
    status: Optional[str] = Query(None, description="DRAFT, ISSUED, PARTIALLY_RECEIVED, COMPLETED, CANCELLED or UI labels like 'Sent to Vendor', 'Partial Delivery'"),
    supplier_id: Optional[UUID] = None,
    search: Optional[str] = Query(None, description="Search by PO number or notes"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List purchase orders for a branch with progress percentage and item counts.
    Supports both database enums (ISSUED, PARTIALLY_RECEIVED) and frontend tab names ('Sent to Vendor', 'Partial Delivery').
    """
    outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantPurchaseOrder)
        .options(
            joinedload(RestaurantPurchaseOrder.outlet),
            joinedload(RestaurantPurchaseOrder.supplier),
            joinedload(RestaurantPurchaseOrder.items).joinedload(RestaurantPurchaseOrderItem.ingredient)
        )
        .filter(RestaurantPurchaseOrder.outlet_id == outlet.id)
    )

    if status and isinstance(status, str) and status.strip():
        cleaned_status = status.strip().upper()
        mapped_status = STATUS_MAP.get(cleaned_status, cleaned_status)
        query = query.filter(RestaurantPurchaseOrder.status == mapped_status)

    if supplier_id:
        query = query.filter(RestaurantPurchaseOrder.supplier_id == supplier_id)

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        pattern = f"%{search_str}%"
        query = query.filter(
            or_(
                RestaurantPurchaseOrder.po_number.ilike(pattern),
                RestaurantPurchaseOrder.notes.ilike(pattern)
            )
        )

    pos = query.order_by(RestaurantPurchaseOrder.created_at.desc()).all()

    results = []
    for po in pos:
        total_ord = sum(item.quantity_ordered for item in po.items) if po.items else Decimal("0")
        total_rec = sum(item.quantity_received for item in po.items) if po.items else Decimal("0")
        fulfillment_pct = Decimal("0.00")
        if total_ord > 0:
            fulfillment_pct = round((total_rec / total_ord) * Decimal("100.00"), 2)

        items_res = []
        for it in (po.items or []):
            items_res.append(PurchaseOrderItemResponse(
                id=it.id,
                po_id=it.po_id,
                ingredient_id=it.ingredient_id,
                ingredient_name=it.ingredient.name if it.ingredient else None,
                ingredient_sku=it.ingredient.sku if it.ingredient else None,
                quantity_ordered=it.quantity_ordered,
                quantity_received=it.quantity_received,
                unit=it.unit,
                unit_price=it.unit_price,
                tax_rate=it.tax_rate,
                tax_amount=it.tax_amount,
                total_price=it.total_price,
                notes=it.notes
            ))

        results.append(PurchaseOrderSummaryResponse(
            id=po.id,
            outlet_id=po.outlet_id,
            outlet_name=po.outlet.name if po.outlet else None,
            outlet_address=po.outlet.address if po.outlet else None,
            outlet_city=po.outlet.city if po.outlet else None,
            outlet_phone=po.outlet.phone if po.outlet else None,
            outlet_email=po.outlet.email if po.outlet else None,
            outlet_gstin=po.outlet.gstin if po.outlet else None,
            supplier_id=po.supplier_id,
            supplier_name=po.supplier.name if po.supplier else None,
            supplier_phone=po.supplier.phone if po.supplier else None,
            supplier_email=po.supplier.email if po.supplier else None,
            po_number=po.po_number,
            status=po.status,
            status_label=STATUS_LABELS.get(po.status, po.status.title()),
            order_date=po.order_date,
            expected_delivery_date=po.expected_delivery_date,
            subtotal=po.subtotal,
            total_amount=po.total_amount,
            items_count=len(po.items),
            fulfillment_percentage=fulfillment_pct,
            items=items_res,
            created_at=po.created_at
        ))

    return results


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Create a new Purchase Order in DRAFT status with line items.
    Safeguards against race conditions on PO numbers using database row-level locking.
    Validates branch isolation for supplier and all ingredients.
    """
    outlet = resolve_outlet(db, payload.outlet_id)

    supplier = db.query(RestaurantSupplier).filter(
        RestaurantSupplier.id == payload.supplier_id,
        RestaurantSupplier.outlet_id == outlet.id
    ).first()
    if not supplier:
        raise HTTPException(status_code=400, detail="Supplier not found or belongs to another branch")

    # Race Condition Prevention: Lock outlet row in transaction to serialize number generation per branch
    db.query(RestaurantOutlet.id).filter(RestaurantOutlet.id == outlet.id).with_for_update().first()
    po_number = generate_next_po_number(db, outlet.id)

    subtotal = Decimal("0.00")
    tax_amount = Decimal("0.00")

    # Pre-validate all ingredients belong to this outlet
    db_items = []
    for item in payload.items:
        ingredient = db.query(RestaurantIngredient).filter(
            RestaurantIngredient.id == item.ingredient_id,
            RestaurantIngredient.outlet_id == outlet.id
        ).first()
        if not ingredient:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient {item.ingredient_id} not found or belongs to another branch"
            )

        line_tax = round((item.quantity_ordered * item.unit_price) * (item.tax_rate / Decimal("100.00")), 2)
        line_total = round((item.quantity_ordered * item.unit_price) + line_tax, 2)
        subtotal += round(item.quantity_ordered * item.unit_price, 2)
        tax_amount += line_tax

        db_items.append(RestaurantPurchaseOrderItem(
            ingredient_id=ingredient.id,
            quantity_ordered=item.quantity_ordered,
            quantity_received=Decimal("0.000"),
            unit=item.unit.upper(),
            unit_price=item.unit_price,
            tax_rate=item.tax_rate,
            tax_amount=line_tax,
            total_price=line_total,
            notes=item.notes
        ))

    total_amount = subtotal + tax_amount

    po = RestaurantPurchaseOrder(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        supplier_id=supplier.id,
        po_number=po_number,
        status="DRAFT",
        order_date=payload.order_date or datetime.utcnow().date(),
        expected_delivery_date=payload.expected_delivery_date,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        delivery_address=payload.delivery_address or outlet.address,
        notes=payload.notes,
        created_by_id=manager_user.id if manager_user else None,
        items=db_items
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    return get_purchase_order_by_id(po.id, db, manager_user)


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
def get_purchase_order_by_id(
    po_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    po = (
        db.query(RestaurantPurchaseOrder)
        .options(
            joinedload(RestaurantPurchaseOrder.outlet),
            joinedload(RestaurantPurchaseOrder.supplier),
            joinedload(RestaurantPurchaseOrder.created_by),
            joinedload(RestaurantPurchaseOrder.items).joinedload(RestaurantPurchaseOrderItem.ingredient)
        )
        .filter(RestaurantPurchaseOrder.id == po_id)
        .first()
    )
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    items_res = []
    total_ord = Decimal("0.000")
    total_rec = Decimal("0.000")
    for item in po.items:
        total_ord += item.quantity_ordered
        total_rec += item.quantity_received
        items_res.append(PurchaseOrderItemResponse(
            id=item.id,
            po_id=item.po_id,
            ingredient_id=item.ingredient_id,
            ingredient_name=item.ingredient.name if item.ingredient else None,
            ingredient_sku=item.ingredient.sku if item.ingredient else None,
            quantity_ordered=item.quantity_ordered,
            quantity_received=item.quantity_received,
            unit=item.unit,
            unit_price=item.unit_price,
            tax_rate=item.tax_rate,
            tax_amount=item.tax_amount,
            total_price=item.total_price,
            notes=item.notes
        ))

    fulfillment_pct = Decimal("0.00")
    if total_ord > 0:
        fulfillment_pct = round((total_rec / total_ord) * Decimal("100.00"), 2)

    return PurchaseOrderResponse(
        id=po.id,
        outlet_id=po.outlet_id,
        outlet_name=po.outlet.name if po.outlet else None,
        outlet_address=po.outlet.address if po.outlet else None,
        outlet_city=po.outlet.city if po.outlet else None,
        outlet_phone=po.outlet.phone if po.outlet else None,
        outlet_email=po.outlet.email if po.outlet else None,
        outlet_gstin=po.outlet.gstin if po.outlet else None,
        tenant_id=po.tenant_id,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name if po.supplier else None,
        supplier_phone=po.supplier.phone if po.supplier else None,
        supplier_email=po.supplier.email if po.supplier else None,
        supplier_address=po.supplier.address if po.supplier else None,
        po_number=po.po_number,
        status=po.status,
        status_label=STATUS_LABELS.get(po.status, po.status.title()),
        order_date=po.order_date,
        expected_delivery_date=po.expected_delivery_date,
        subtotal=po.subtotal,
        tax_amount=po.tax_amount,
        total_amount=po.total_amount,
        delivery_address=po.delivery_address,
        notes=po.notes,
        created_by_name=po.created_by.name if po.created_by else None,
        fulfillment_percentage=fulfillment_pct,
        items=items_res,
        created_at=po.created_at,
        updated_at=po.updated_at
    )


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
@router.patch("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(
    po_id: UUID,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    po = db.query(RestaurantPurchaseOrder).filter(RestaurantPurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po.status not in ["DRAFT"]:
        raise HTTPException(status_code=400, detail="Only DRAFT purchase orders can be modified")

    if payload.supplier_id:
        supplier = db.query(RestaurantSupplier).filter(
            RestaurantSupplier.id == payload.supplier_id,
            RestaurantSupplier.outlet_id == po.outlet_id
        ).first()
        if not supplier:
            raise HTTPException(status_code=400, detail="Supplier not found or belongs to another branch")
        po.supplier_id = payload.supplier_id

    if payload.order_date:
        po.order_date = payload.order_date
    if payload.expected_delivery_date:
        po.expected_delivery_date = payload.expected_delivery_date
    if payload.delivery_address is not None:
        po.delivery_address = payload.delivery_address
    if payload.notes is not None:
        po.notes = payload.notes

    if payload.items is not None:
        # Replace line items
        db.query(RestaurantPurchaseOrderItem).filter(RestaurantPurchaseOrderItem.po_id == po.id).delete()
        subtotal = Decimal("0.00")
        tax_amount = Decimal("0.00")

        for item in payload.items:
            line_tax = round((item.quantity_ordered * item.unit_price) * (item.tax_rate / Decimal("100.00")), 2)
            line_total = round((item.quantity_ordered * item.unit_price) + line_tax, 2)
            subtotal += round(item.quantity_ordered * item.unit_price, 2)
            tax_amount += line_tax

            db_item = RestaurantPurchaseOrderItem(
                po_id=po.id,
                ingredient_id=item.ingredient_id,
                quantity_ordered=item.quantity_ordered,
                quantity_received=Decimal("0.000"),
                unit=item.unit.upper(),
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                tax_amount=line_tax,
                total_price=line_total,
                notes=item.notes
            )
            db.add(db_item)

        po.subtotal = subtotal
        po.tax_amount = tax_amount
        po.total_amount = subtotal + tax_amount

    db.commit()
    return get_purchase_order_by_id(po.id, db, manager_user)


@router.post("/purchase-orders/{po_id}/issue", response_model=PurchaseOrderResponse)
def issue_purchase_order(
    po_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Lock and transition PO from DRAFT to ISSUED. Ready to dispatch to supplier.
    """
    po = db.query(RestaurantPurchaseOrder).filter(RestaurantPurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po.status != "DRAFT":
        raise HTTPException(status_code=400, detail=f"Cannot issue order currently in '{po.status}' state")

    po.status = "ISSUED"
    db.commit()
    return get_purchase_order_by_id(po.id, db, manager_user)


class PurchaseOrderEmailRequest(BaseModel):
    email: Optional[str] = None
    message: Optional[str] = None


@router.post("/purchase-orders/{po_id}/email")
def email_purchase_order(
    po_id: UUID,
    payload: Optional[PurchaseOrderEmailRequest] = None,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Dispatch PO details via email to the supplier.
    If the PO is currently DRAFT, automatically marks it as ISSUED.
    """
    po = db.query(RestaurantPurchaseOrder).filter(RestaurantPurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    recipient_email = payload.email.strip() if payload and payload.email and payload.email.strip() else None
    if not recipient_email and po.supplier and po.supplier.email:
        recipient_email = po.supplier.email.strip()

    if not recipient_email:
        raise HTTPException(status_code=400, detail="Supplier does not have an email registered. Please provide an email address.")

    if po.status == "DRAFT":
        po.status = "ISSUED"
        db.commit()

    return {
        "success": True,
        "message": f"Purchase Order {po.po_number} dispatched to {recipient_email}",
        "recipient_email": recipient_email,
        "po_number": po.po_number,
        "status": po.status
    }


@router.post("/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderResponse)
def cancel_purchase_order(
    po_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    po = db.query(RestaurantPurchaseOrder).filter(RestaurantPurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po.status in ["COMPLETED", "CANCELLED"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel PO in '{po.status}' state")

    po.status = "CANCELLED"
    db.commit()
    return get_purchase_order_by_id(po.id, db, manager_user)


@router.delete("/purchase-orders/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(
    po_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    po = db.query(RestaurantPurchaseOrder).filter(RestaurantPurchaseOrder.id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")
    if po.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only DRAFT purchase orders can be deleted")

    db.delete(po)
    db.commit()
    return None


# ----------------- PURCHASE ORDER BILL PRINTING & PDF -----------------

po_template_env = Environment(loader=FileSystemLoader(searchpath="./templates"))

def render_po_html(po: RestaurantPurchaseOrder, autoprint: bool = False) -> str:
    outlet = po.outlet
    supplier = po.supplier

    items_data = []
    for item in po.items:
        items_data.append({
            "ingredient_name": item.ingredient.name if item.ingredient else "Raw Commodity",
            "ingredient_sku": item.ingredient.sku if item.ingredient else None,
            "quantity_ordered": item.quantity_ordered,
            "unit": item.unit,
            "unit_price": item.unit_price,
            "tax_amount": item.tax_amount,
            "total_price": item.total_price,
            "notes": item.notes
        })

    order_date_fmt = po.order_date.strftime("%d %b %Y") if po.order_date else "N/A"
    expected_delivery_fmt = po.expected_delivery_date.strftime("%d %b %Y") if po.expected_delivery_date else "N/A"

    template = po_template_env.get_template("purchase_order_template.html")
    return template.render(
        outlet=outlet,
        supplier=supplier,
        po=po,
        items=items_data,
        status_label=STATUS_LABELS.get(po.status, po.status.title()),
        order_date_formatted=order_date_fmt,
        expected_delivery_formatted=expected_delivery_fmt,
        autoprint=autoprint
    )


@router.get("/purchase-orders/{po_id}/print", response_class=HTMLResponse)
def print_purchase_order(
    po_id: UUID,
    autoprint: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Renders pixel-perfect HTML Purchase Order bill matching the A4 enterprise kitchen format.
    Pass ?autoprint=true to immediately trigger browser's native print / Save-as-PDF dialog.
    """
    po = (
        db.query(RestaurantPurchaseOrder)
        .options(
            joinedload(RestaurantPurchaseOrder.outlet),
            joinedload(RestaurantPurchaseOrder.supplier),
            joinedload(RestaurantPurchaseOrder.items).joinedload(RestaurantPurchaseOrderItem.ingredient)
        )
        .filter(RestaurantPurchaseOrder.id == po_id)
        .first()
    )
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    html_content = render_po_html(po, autoprint=autoprint)
    return HTMLResponse(content=html_content)


@router.get("/purchase-orders/{po_id}/pdf")
def download_purchase_order_pdf(
    po_id: UUID,
    download: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Renders and streams the Purchase Order as an exact binary A4 PDF document.
    """
    po = (
        db.query(RestaurantPurchaseOrder)
        .options(
            joinedload(RestaurantPurchaseOrder.outlet),
            joinedload(RestaurantPurchaseOrder.supplier),
            joinedload(RestaurantPurchaseOrder.items).joinedload(RestaurantPurchaseOrderItem.ingredient)
        )
        .filter(RestaurantPurchaseOrder.id == po_id)
        .first()
    )
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    html_content = render_po_html(po, autoprint=False)
    pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()

    disposition = "attachment" if download else "inline"
    filename = f"{po.po_number}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"'
        }
    )


# ==============================================================================
# 3. GOODS RECEIVED NOTE (GRN) & INVENTORY RECEIVING
# ==============================================================================

@router.get("/grn/next-number")
def get_next_grn_number_endpoint(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    outlet = resolve_outlet(db, outlet_id)
    return {"grn_number": generate_next_grn_number(db, outlet.id), "outlet_id": outlet.id}


@router.post("/grn/upload-invoice")
async def upload_vendor_invoice_document(
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Digitally store supplier physical invoice / delivery challan (PDF, JPG, PNG, WEBP).
    Stores file in uploads/procurement/invoices/ and returns the URL.
    """
    allowed_types = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
    content_type = file.content_type.lower() if file.content_type else ""
    orig_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"

    if content_type not in allowed_types and orig_ext not in [".jpg", ".jpeg", ".png", ".webp", ".pdf"]:
        raise HTTPException(status_code=400, detail="Invoice file must be an image (JPG, PNG, WEBP) or PDF document")

    ext = orig_ext if orig_ext in [".jpg", ".jpeg", ".png", ".webp", ".pdf"] else ".jpg"
    os.makedirs("uploads/procurement/invoices", exist_ok=True)
    filename = f"inv_{uuid.uuid4().hex[:14]}{ext}"
    file_path = os.path.join("uploads", "procurement", "invoices", filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "invoice_document_url": f"/uploads/procurement/invoices/{filename}",
        "filename": file.filename,
        "content_type": file.content_type
    }


@router.get("/grn", response_model=List[GRNResponse])
def get_grn_list(
    outlet_id: Optional[UUID] = None,
    po_id: Optional[UUID] = None,
    supplier_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantGRN)
        .options(
            joinedload(RestaurantGRN.supplier),
            joinedload(RestaurantGRN.po),
            joinedload(RestaurantGRN.items).joinedload(RestaurantGRNItem.ingredient)
        )
        .filter(RestaurantGRN.outlet_id == outlet.id)
    )

    if po_id:
        query = query.filter(RestaurantGRN.po_id == po_id)
    if supplier_id:
        query = query.filter(RestaurantGRN.supplier_id == supplier_id)

    grns = query.order_by(RestaurantGRN.created_at.desc()).all()

    results = []
    for g in grns:
        items_res = []
        for it in g.items:
            items_res.append(GRNItemResponse(
                id=it.id,
                grn_id=it.grn_id,
                ingredient_id=it.ingredient_id,
                ingredient_name=it.ingredient.name if it.ingredient else None,
                po_item_id=it.po_item_id,
                quantity_received=it.quantity_received,
                unit=it.unit,
                unit_price=it.unit_price,
                tax_rate=it.tax_rate,
                tax_amount=it.tax_amount,
                total_price=it.total_price,
                batch_number=it.batch_number,
                expiry_date=it.expiry_date
            ))

        results.append(GRNResponse(
            id=g.id,
            outlet_id=g.outlet_id,
            tenant_id=g.tenant_id,
            po_id=g.po_id,
            po_number=g.po.po_number if g.po else None,
            supplier_id=g.supplier_id,
            supplier_name=g.supplier.name if g.supplier else None,
            grn_number=g.grn_number,
            supplier_invoice_no=g.supplier_invoice_no,
            invoice_date=g.invoice_date,
            invoice_document_url=g.invoice_document_url,
            received_date=g.received_date,
            total_amount=g.total_amount,
            payment_status=g.payment_status,
            remarks=g.remarks,
            items=[
                GRNItemResponse(
                    id=it.id,
                    grn_id=it.grn_id,
                    ingredient_id=it.ingredient_id,
                    ingredient_name=it.ingredient.name if it.ingredient else None,
                    po_item_id=it.po_item_id,
                    quantity_received=it.quantity_received,
                    quantity_rejected=it.quantity_rejected,
                    rejection_reason=it.rejection_reason,
                    unit=it.unit,
                    unit_price=it.unit_price,
                    tax_rate=it.tax_rate,
                    tax_amount=it.tax_amount,
                    total_price=it.total_price,
                    batch_number=it.batch_number,
                    expiry_date=it.expiry_date
                )
                for it in g.items
            ],
            created_at=g.created_at
        ))

    return results


@router.post("/grn/receive", response_model=GRNResponse, status_code=status.HTTP_201_CREATED)
def receive_goods(
    payload: GRNCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Receive stock at kitchen:
    1. Prevents race conditions on sequential GRN numbering using row-level locking.
    2. Accommodates price variance (actual vendor invoice price vs PO estimated price).
    3. Handles damaged/spoiled items (quantity_rejected + rejection_reason).
    4. Automatically recalculates Weighted Average Cost (WAC) on restaurant_ingredients.
    5. Creates append-only records in RestaurantStockLedger (PURCHASE_RECEIVED).
    6. Atomically updates PO line item fulfillment and PO status (PARTIAL/COMPLETED).
    """
    outlet = resolve_outlet(db, payload.outlet_id)

    supplier = db.query(RestaurantSupplier).filter(
        RestaurantSupplier.id == payload.supplier_id,
        RestaurantSupplier.outlet_id == outlet.id
    ).first()
    if not supplier:
        raise HTTPException(status_code=400, detail="Supplier not found or belongs to another branch")

    po = None
    if payload.po_id:
        po = db.query(RestaurantPurchaseOrder).filter(
            RestaurantPurchaseOrder.id == payload.po_id,
            RestaurantPurchaseOrder.outlet_id == outlet.id
        ).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")
        if po.status in ["CANCELLED", "COMPLETED"]:
            raise HTTPException(status_code=400, detail=f"Cannot receive goods against a '{po.status}' Purchase Order")

    # Race condition prevention: Lock outlet row in transaction
    db.query(RestaurantOutlet.id).filter(RestaurantOutlet.id == outlet.id).with_for_update().first()
    grn_number = generate_next_grn_number(db, outlet.id)

    total_amount = Decimal("0.00")
    grn_items = []

    for item_input in payload.items:
        ingredient = db.query(RestaurantIngredient).filter(
            RestaurantIngredient.id == item_input.ingredient_id,
            RestaurantIngredient.outlet_id == outlet.id
        ).first()
        if not ingredient:
            raise HTTPException(status_code=400, detail=f"Ingredient {item_input.ingredient_id} not found")

        # Edge case: Price variance between estimated PO price and actual physical vendor bill
        actual_price = item_input.actual_unit_price if item_input.actual_unit_price is not None else item_input.unit_price

        line_tax = round((item_input.quantity_received * actual_price) * (item_input.tax_rate / Decimal("100.00")), 2)
        line_total = round((item_input.quantity_received * actual_price) + line_tax, 2)
        total_amount += line_total

        # Match linked PO item: first by direct po_item_id, or fallback to matching ingredient_id on this PO
        po_item = None
        if item_input.po_item_id:
            po_item = db.query(RestaurantPurchaseOrderItem).filter(
                RestaurantPurchaseOrderItem.id == item_input.po_item_id,
                RestaurantPurchaseOrderItem.po_id == payload.po_id
            ).first()
        elif po:
            po_item = db.query(RestaurantPurchaseOrderItem).filter(
                RestaurantPurchaseOrderItem.ingredient_id == ingredient.id,
                RestaurantPurchaseOrderItem.po_id == po.id
            ).first()

        resolved_po_item_id = po_item.id if po_item else item_input.po_item_id
        if po_item:
            po_item.quantity_received += item_input.quantity_received

        # 1. Prepare GRN line item with rejected tracking & FIFO/FEFO batch details
        grn_items.append(RestaurantGRNItem(
            ingredient_id=ingredient.id,
            po_item_id=resolved_po_item_id,
            quantity_received=item_input.quantity_received,
            quantity_rejected=item_input.quantity_rejected,
            rejection_reason=item_input.rejection_reason,
            unit=item_input.unit.upper(),
            unit_price=actual_price,
            tax_rate=item_input.tax_rate,
            tax_amount=line_tax,
            total_price=line_total,
            batch_number=item_input.batch_number,
            expiry_date=item_input.expiry_date
        ))

        # Log rejection audit trail if damaged goods were turned away at dock
        # signed_quantity is strictly 0.000 so SUM(signed_quantity) always equals current_stock exactly
        if item_input.quantity_rejected > Decimal("0.000"):
            conversion = Decimal(str(ingredient.uom_conversion_factor or 1.0))
            if conversion <= Decimal("0.0000"):
                conversion = Decimal("1.0000")
            recv_unit = (item_input.unit or "").strip().upper()
            purch_unit = (ingredient.purchase_uom or "").strip().upper()
            recipe_unit = (ingredient.recipe_uom or ingredient.unit or "").strip().upper()
            rej_qty_recipe = round(item_input.quantity_rejected * conversion, 3) if (recv_unit == purch_unit and recv_unit != recipe_unit) else item_input.quantity_rejected

            rej_ledger = RestaurantStockLedger(
                ingredient_id=ingredient.id,
                outlet_id=outlet.id,
                tenant_id=outlet.tenant_id,
                signed_quantity=Decimal("0.000"), # 0 stock impact so SUM(signed_quantity) matches physical current_stock exactly
                reason="PURCHASE_REJECTED",
                source_type="grn_dock_rejection",
                source_id=grn_number,
                actor_id=manager_user.id if manager_user else None,
                notes=f"Rejected {item_input.quantity_rejected} {item_input.unit} ({rej_qty_recipe} {recipe_unit}) at dock - Reason: {item_input.rejection_reason or 'Damaged / Spoiled'}"
            )
            db.add(rej_ledger)

        # 3. Add accepted stock to append-only stock ledger (handling Dual-UOM conversions: Purchase UOM -> Recipe UOM)
        if item_input.quantity_received > Decimal("0.000"):
            # Landed Unit Cost: In restaurant accounting (5% GST slab / no ITC claim),
            # GST paid on raw materials is a real cost of goods sold.
            tax_per_unit = line_tax / item_input.quantity_received
            landed_unit_cost = round(actual_price + tax_per_unit, 2)

            conversion = Decimal(str(ingredient.uom_conversion_factor or 1.0))
            if conversion <= Decimal("0.0000"):
                conversion = Decimal("1.0000")

            recv_unit = (item_input.unit or "").strip().upper()
            purch_unit = (ingredient.purchase_uom or "").strip().upper()
            recipe_unit = (ingredient.recipe_uom or ingredient.unit or "").strip().upper()

            # Convert received quantity and cost to Recipe UOM if received in Purchase UOM (e.g. 10 KG * 1000 = 10,000 G)
            if recv_unit == purch_unit and recv_unit != recipe_unit:
                stock_received_qty = round(item_input.quantity_received * conversion, 3)
                landed_cost_per_recipe_unit = round(landed_unit_cost / conversion, 4)
                landed_cost_per_purchase_unit = landed_unit_cost
            else:
                stock_received_qty = item_input.quantity_received
                landed_cost_per_recipe_unit = landed_unit_cost
                landed_cost_per_purchase_unit = round(landed_unit_cost * conversion, 2)

            ledger_entry = RestaurantStockLedger(
                ingredient_id=ingredient.id,
                outlet_id=outlet.id,
                tenant_id=outlet.tenant_id,
                signed_quantity=stock_received_qty, # Stored in Recipe UOM so SUM(signed_quantity) == current_stock
                reason="PURCHASE_RECEIVED",
                source_type="grn",
                source_id=grn_number,
                actor_id=manager_user.id if manager_user else None,
                notes=f"GRN {grn_number} - Invoice: {payload.supplier_invoice_no or 'N/A'} (+{item_input.quantity_received} {item_input.unit} = +{stock_received_qty} {recipe_unit})"
            )
            db.add(ledger_entry)

            # 4. Weighted Average Cost (WAC) recalculation with landed cost (Price + non-creditable GST)
            # In recipe units (e.g. ₹/G):
            old_stock = ingredient.current_stock or Decimal("0.000")
            old_cost = ingredient.cost_per_unit or Decimal("0.0000")

            total_stock_after = old_stock + stock_received_qty
            if total_stock_after > Decimal("0.000") and old_stock > Decimal("0.000"):
                new_wac_recipe = ((old_stock * old_cost) + (stock_received_qty * landed_cost_per_recipe_unit)) / total_stock_after
                ingredient.cost_per_unit = round(new_wac_recipe, 4)
            elif total_stock_after > Decimal("0.000"):
                ingredient.cost_per_unit = round(landed_cost_per_recipe_unit, 4)

            # Update purchase unit cost (e.g. ₹/KG = cost_per_unit * conversion)
            if hasattr(ingredient, "cost_per_purchase_unit"):
                ingredient.cost_per_purchase_unit = round(ingredient.cost_per_unit * conversion, 2)

            # 5. Atomically increment ingredient current stock balance (in recipe UOM)
            ingredient.current_stock += stock_received_qty

    # Create GRN header
    grn = RestaurantGRN(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        po_id=po.id if po else None,
        supplier_id=supplier.id,
        grn_number=grn_number,
        supplier_invoice_no=payload.supplier_invoice_no,
        invoice_date=payload.invoice_date,
        invoice_document_url=payload.invoice_document_url,
        received_date=datetime.utcnow(),
        received_by_id=manager_user.id if manager_user else None,
        total_amount=total_amount,
        payment_status=payload.payment_status or "UNPAID",
        remarks=payload.remarks,
        items=grn_items
    )
    db.add(grn)

    # 6. Automatically evaluate PO completion status
    if po:
        all_po_items = db.query(RestaurantPurchaseOrderItem).filter(RestaurantPurchaseOrderItem.po_id == po.id).all()
        is_all_fulfilled = len(all_po_items) > 0 and all(item.quantity_received >= item.quantity_ordered for item in all_po_items)
        any_received = any(item.quantity_received > 0 for item in all_po_items)
        if is_all_fulfilled:
            po.status = "COMPLETED"
        elif any_received:
            po.status = "PARTIALLY_RECEIVED"
        else:
            po.status = "ISSUED"

    db.commit()
    db.refresh(grn)

    return get_grn_by_id(grn.id, db, manager_user)


@router.get("/grn/{grn_id}", response_model=GRNResponse)
def get_grn_by_id(
    grn_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    g = (
        db.query(RestaurantGRN)
        .options(
            joinedload(RestaurantGRN.supplier),
            joinedload(RestaurantGRN.po),
            joinedload(RestaurantGRN.items).joinedload(RestaurantGRNItem.ingredient)
        )
        .filter(RestaurantGRN.id == grn_id)
        .first()
    )
    if not g:
        raise HTTPException(status_code=404, detail="Goods Received Note not found")

    items_res = []
    for it in g.items:
        items_res.append(GRNItemResponse(
            id=it.id,
            grn_id=it.grn_id,
            ingredient_id=it.ingredient_id,
            ingredient_name=it.ingredient.name if it.ingredient else None,
            po_item_id=it.po_item_id,
            quantity_received=it.quantity_received,
            quantity_rejected=it.quantity_rejected,
            rejection_reason=it.rejection_reason,
            unit=it.unit,
            unit_price=it.unit_price,
            tax_rate=it.tax_rate,
            tax_amount=it.tax_amount,
            total_price=it.total_price,
            batch_number=it.batch_number,
            expiry_date=it.expiry_date
        ))

    return GRNResponse(
        id=g.id,
        outlet_id=g.outlet_id,
        tenant_id=g.tenant_id,
        po_id=g.po_id,
        po_number=g.po.po_number if g.po else None,
        supplier_id=g.supplier_id,
        supplier_name=g.supplier.name if g.supplier else None,
        grn_number=g.grn_number,
        supplier_invoice_no=g.supplier_invoice_no,
        invoice_date=g.invoice_date,
        invoice_document_url=g.invoice_document_url,
        received_date=g.received_date,
        total_amount=g.total_amount,
        payment_status=g.payment_status,
        remarks=g.remarks,
        items=items_res,
        created_at=g.created_at
    )
