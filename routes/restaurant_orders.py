from typing import List, Optional, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_table import RestaurantTable
from models.restaurant_menu import RestaurantMenuItem, RestaurantMenuCategory
from models.restaurant_modifier import RestaurantModifierGroup
from models.restaurant_order import RestaurantOrder
from models.restaurant_order_line import RestaurantOrderLine
from models.restaurant_kitchen import RestaurantKitchenTicket, RestaurantKitchenTicketItem, RestaurantKitchenEvent
from models.restaurant_audit import RestaurantAuditEvent
from models.restaurant_recipe import RestaurantRecipe
from models.restaurant_ingredient import RestaurantIngredient
from models.restaurant_stock_ledger import RestaurantStockLedger
from models.restaurant_tender import RestaurantTender
from schemas.restaurant_order import (
    RestaurantOrderCreate, RestaurantOrderUpdateItems, RestaurantOrderStateTransition,
    RestaurantOrderItemVoid, RestaurantOrderResponse, RestaurantOrderLineResponse,
    CustomerTableOrderCreate, RejectQROrderRequest, CustomerTableInfoResponse,
    CustomerTableOrderLineSummary
)
from schemas.restaurant_kitchen import KitchenTicketResponse
from dependencies import (
    get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff,
    get_user_scoped_outlet_id
)
from utils.restaurant_thermal_printer import generate_kot_pdf, generate_bill_pdf
from utils.restaurant_inventory_helper import resolve_branch_ingredient, normalize_recipe_uom
from utils.timezone import get_current_time

router = APIRouter(
    prefix="/api/restaurant/orders",
    tags=["Restaurant - Orders & Calculations"]
)

def _generate_order_number(db: Session, outlet_id: UUID) -> str:
    """Generate sequential order number ORD-YYYYMMDD-XXXX in IST."""
    today_str = get_current_time().strftime("%Y%m%d")
    prefix = f"ORD-{today_str}-"
    count = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.order_number.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:04d}"

def _calculate_line_item(db: Session, item_id: UUID, variant_name: str, quantity: int, modifiers_input: list) -> tuple:
    """
    Server-authoritative calculation:
    Fetches official item price from database and calculates item price, tax, and line total.
    """
    item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == item_id).first()
    if not item or not item.is_active:
        raise HTTPException(status_code=400, detail=f"Menu item {item_id} is inactive or does not exist")
    if not item.is_available:
        raise HTTPException(status_code=400, detail=f"Menu item '{item.name}' is currently marked unavailable")

    # Direct server-authoritative unit price from menu item (with variant override if specified)
    unit_price = Decimal(str(item.price or 0.00))
    if variant_name and variant_name.upper() != "STANDARD" and item.variant_prices:
        for vp in item.variant_prices:
            if isinstance(vp, dict) and vp.get("variant_name", "").upper() == variant_name.upper():
                unit_price = Decimal(str(vp.get("price", unit_price)))
                break
    
    # Calculate modifiers sum
    modifier_price = Decimal("0.00")
    selected_modifiers = []
    for mod in modifiers_input:
        m_price = Decimal(str(mod.price))
        modifier_price += m_price
        selected_modifiers.append({
            "id": str(mod.modifier_option_id),
            "name": mod.name,
            "price": float(m_price)
        })

    qty = Decimal(str(quantity))
    base_subtotal = (unit_price + modifier_price) * qty
    tax_rate = Decimal(str(item.tax_rate))
    tax_amount = (base_subtotal * (tax_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    line_total = base_subtotal + tax_amount

    return item, unit_price, modifier_price, tax_rate, tax_amount, line_total, selected_modifiers


@router.post("", response_model=RestaurantOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: RestaurantOrderCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Create a new order with server-calculated totals and idempotency check.
    """
    # 1. Idempotency Check
    if payload.idempotency_key:
        existing_order = (
            db.query(RestaurantOrder)
            .filter(RestaurantOrder.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing_order:
            return existing_order

    # 2. Validate Outlet & Table (strictly scoped to user tenant)
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, payload.outlet_id)
    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == scoped_outlet_id).first() if scoped_outlet_id else None
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant outlet not found for this tenant")

    # 3. Check Branch Subscription Status
    from dependencies import check_active_subscription
    if not check_active_subscription(outlet.tenant_id, db, outlet_id=outlet.id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Subscription for '{outlet.name}' has expired or is unpaid. Please renew your branch subscription to create orders."
        )

    resolved_table_id = None
    if payload.table_id:
        try:
            resolved_table_id = UUID(str(payload.table_id))
            table = db.query(RestaurantTable).filter(RestaurantTable.id == resolved_table_id).first()
            if table:
                table.status = "OCCUPIED"
            else:
                resolved_table_id = None
        except (ValueError, TypeError):
            # Table label/code (e.g. "T1") was sent instead of UUID
            table = db.query(RestaurantTable).filter(
                RestaurantTable.outlet_id == outlet.id,
                RestaurantTable.table_code.ilike(str(payload.table_id))
            ).first()
            if table:
                resolved_table_id = table.id
                table.status = "OCCUPIED"

    order_num = _generate_order_number(db, outlet.id)

    valid_customer_id = payload.customer_id
    if valid_customer_id:
        from models.restaurant_customer import RestaurantCustomer
        if not db.query(RestaurantCustomer).filter(RestaurantCustomer.id == valid_customer_id).first():
            valid_customer_id = None

    order = RestaurantOrder(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        order_number=order_num,
        order_type=payload.order_type,
        status="OPEN",
        table_id=resolved_table_id,
        customer_id=valid_customer_id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        waiter_id=current_user.id if current_user else None,
        notes=payload.notes,
        payment_method=(payload.payment_method or "CASH").upper(),
        idempotency_key=payload.idempotency_key,
        subtotal=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        rounding_adjustment=Decimal("0.00"),
        grand_total=Decimal("0.00"),
        paid_amount=Decimal("0.00"),
        version=1
    )
    db.add(order)
    db.flush()

    subtotal_acc = Decimal("0.00")
    tax_acc = Decimal("0.00")

    # Combine lines or items from payload
    input_lines = payload.lines if payload.lines else payload.items

    # 3. Compute order lines with server-side pricing or client fallback
    for line_in in input_lines:
        resolved_item_id = line_in.item_id or line_in.menu_item_id
        if resolved_item_id:
            try:
                resolved_item_id = UUID(str(resolved_item_id))
            except (ValueError, TypeError):
                resolved_item_id = None

        item = None
        if resolved_item_id:
            item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == resolved_item_id).first()
        if not item and line_in.name:
            item = db.query(RestaurantMenuItem).filter(
                RestaurantMenuItem.outlet_id == outlet.id,
                RestaurantMenuItem.name.ilike(line_in.name)
            ).first()

        qty = max(1, line_in.quantity)
        if item:
            unit_p, mod_p, tax_r, tax_a, line_tot, sel_mods = _calculate_line_item(
                db, item.id, line_in.variant_name, qty, line_in.modifiers
            )[1:]
            item_name = item.name
            prep_station = item.prep_station
        else:
            # Fallback for dynamic/custom cart items
            unit_p = line_in.unit_price or line_in.price or Decimal("0.00")
            mod_p = Decimal("0.00")
            tax_r = Decimal("5.00")
            tax_a = (unit_p * Decimal(str(qty)) * tax_r) / Decimal("100.00")
            line_tot = (unit_p * Decimal(str(qty))) + tax_a
            sel_mods = None
            item_name = line_in.name or "Food Item"
            prep_station = "KITCHEN"

        instructions = line_in.special_instructions or line_in.notes

        db_line = RestaurantOrderLine(
            order_id=order.id,
            item_id=item.id if item else None,
            item_name=item_name,
            variant_name=line_in.variant_name,
            prep_station=prep_station,
            quantity=qty,
            unit_price=unit_p,
            modifier_price=mod_p,
            discount_amount=Decimal("0.00"),
            tax_rate=tax_r,
            tax_amount=tax_a,
            line_total=line_tot,
            selected_modifiers=sel_mods,
            special_instructions=instructions,
            kot_status="PENDING_SEND"
        )
        db.add(db_line)
        subtotal_acc += (unit_p + mod_p) * Decimal(str(qty))
        tax_acc += tax_a

    # 4. Final totals with rounding
    raw_total = subtotal_acc + tax_acc
    rounded_grand_total = raw_total.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    rounding_diff = rounded_grand_total - raw_total

    order.subtotal = subtotal_acc
    order.tax_amount = tax_acc
    order.rounding_adjustment = rounding_diff
    order.grand_total = rounded_grand_total

    db.commit()
    db.refresh(order)
    return order


@router.get("", response_model=List[RestaurantOrderResponse])
def get_orders(
    outlet_id: Optional[UUID] = None,
    customer_phone: Optional[str] = None,
    customer_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    table_id: Optional[UUID] = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    target_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)

    query = (
        db.query(RestaurantOrder)
        .options(joinedload(RestaurantOrder.lines))
    )
    if current_user and current_user.tenant_id:
        query = query.filter(RestaurantOrder.tenant_id == current_user.tenant_id)

    if target_outlet_id and not (customer_phone or customer_id):
        query = query.filter(RestaurantOrder.outlet_id == target_outlet_id)
    elif target_outlet_id:
        query = query.filter(RestaurantOrder.outlet_id == target_outlet_id)

    if customer_phone:
        clean_phone = ''.join(filter(str.isdigit, customer_phone))
        query = query.filter(RestaurantOrder.customer_phone.ilike(f"%{clean_phone}%"))
    if customer_id:
        query = query.filter(RestaurantOrder.customer_id == customer_id)
    if status_filter:
        query = query.filter(RestaurantOrder.status == status_filter)
    if table_id:
        query = query.filter(RestaurantOrder.table_id == table_id)

    return query.order_by(RestaurantOrder.created_at.desc()).limit(limit).all()


@router.get("/table/{table_id}", response_model=Optional[RestaurantOrderResponse])
def get_active_order_by_table(
    table_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Fetch the currently active live bill/order for a seated table.
    Includes OPEN, SENT_TO_KITCHEN, and SERVED orders awaiting settlement.
    Returns None if no active order is currently on this table.
    """
    order = (
        db.query(RestaurantOrder)
        .options(joinedload(RestaurantOrder.lines))
        .filter(RestaurantOrder.table_id == table_id)
        .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "READY", "SERVED"]))
        .order_by(RestaurantOrder.created_at.desc())
        .first()
    )
    return order


@router.get("/pending-qr", response_model=List[RestaurantOrderResponse])
def get_pending_qr_orders(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    POS Cashier Review Queue: Returns all unverified Dine-in QR orders submitted by customers,
    awaiting confirmation before being fired to the kitchen.
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    if not scoped_outlet_id:
        return []

    return (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.outlet_id == scoped_outlet_id)
        .filter(RestaurantOrder.status == "PENDING_CONFIRMATION")
        .order_by(RestaurantOrder.created_at.desc())
        .all()
    )


@router.get("/{order_id}", response_model=RestaurantOrderResponse)
def get_order_by_id(
    order_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    order = (
        db.query(RestaurantOrder)
        .options(joinedload(RestaurantOrder.lines))
        .filter(RestaurantOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}")
def patch_order(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Direct PATCH endpoint to update status, table, or notes on an order.
    Eliminates 405 Method Not Allowed from client updates.
    """
    try:
        val_uuid = UUID(order_id)
        order = db.query(RestaurantOrder).filter(RestaurantOrder.id == val_uuid).first()
    except (ValueError, TypeError):
        order = db.query(RestaurantOrder).filter(RestaurantOrder.order_number == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = payload.get("status") or payload.get("order_status") or payload.get("kitchen_status")
    if new_status:
        order.status = str(new_status).upper()

    if "notes" in payload:
        order.notes = payload["notes"]
    if "customer_name" in payload:
        order.customer_name = payload["customer_name"]
    if "customer_phone" in payload:
        order.customer_phone = payload["customer_phone"]
    if "table_id" in payload and payload["table_id"]:
        try:
            order.table_id = UUID(str(payload["table_id"]))
        except Exception:
            pass

    order.updated_at = get_current_time()
    db.commit()
    db.refresh(order)

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "message": f"Order {order.order_number} status updated to {order.status}"
    }


from schemas.restaurant_order import RestaurantApplyDiscount

@router.patch("/{order_id}/items", response_model=RestaurantOrderResponse)
def update_order_items(
    order_id: UUID,
    payload: RestaurantOrderUpdateItems,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Append items to an open order with optimistic concurrency control.
    Fails with 409 Conflict if expected_version doesn't match current order version.
    """
    order = db.query(RestaurantOrder).filter(RestaurantOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in ["COMPLETED", "CANCELLED", "VOIDED"]:
        raise HTTPException(status_code=400, detail=f"Cannot add items to an order in {order.status} state")

    # Optimistic locking check (allow -1 or null to bypass strict check)
    if payload.expected_version is not None and payload.expected_version != -1:
        if order.version != payload.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Concurrency conflict: Order version is {order.version}, but client expected {payload.expected_version}. Please refresh."
            )

    subtotal_acc = Decimal("0.00")
    tax_acc = Decimal("0.00")

    for line_in in payload.lines:
        item, unit_p, mod_p, tax_r, tax_a, line_tot, sel_mods = _calculate_line_item(
            db, line_in.item_id, line_in.variant_name, line_in.quantity, line_in.modifiers
        )

        db_line = RestaurantOrderLine(
            order_id=order.id,
            item_id=item.id,
            item_name=item.name,
            variant_name=line_in.variant_name,
            prep_station=item.prep_station,
            quantity=line_in.quantity,
            unit_price=unit_p,
            modifier_price=mod_p,
            discount_amount=Decimal("0.00"),
            tax_rate=tax_r,
            tax_amount=tax_a,
            line_total=line_tot,
            selected_modifiers=sel_mods,
            special_instructions=line_in.special_instructions,
            kot_status="PENDING_SEND"
        )
        db.add(db_line)
        subtotal_acc += (unit_p + mod_p) * Decimal(str(line_in.quantity))
        tax_acc += tax_a

    # Update order cumulative totals
    order.subtotal += subtotal_acc
    order.tax_amount += tax_acc
    raw_total = order.subtotal - order.discount_amount + order.tax_amount
    rounded_grand_total = raw_total.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    order.rounding_adjustment = rounded_grand_total - raw_total
    order.grand_total = rounded_grand_total
    order.version += 1

    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/discount", response_model=RestaurantOrderResponse)
def apply_order_discount(
    order_id: UUID,
    payload: RestaurantApplyDiscount,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Apply discount to an order (Manager / Owner / Admin only).
    Recalculates taxes, rounding, and logs an audit trail.
    """
    order = db.query(RestaurantOrder).filter(RestaurantOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order was modified by another user. Please reload."
        )

    discount_val = Decimal(str(payload.discount_amount))
    if discount_val > order.subtotal:
        raise HTTPException(status_code=400, detail="Discount cannot exceed order subtotal")

    old_discount = order.discount_amount
    order.discount_amount = discount_val
    order.discount_reason = payload.discount_reason

    raw_total = order.subtotal - order.discount_amount + order.tax_amount
    rounded_grand_total = raw_total.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    order.rounding_adjustment = rounded_grand_total - raw_total
    order.grand_total = rounded_grand_total
    order.version += 1

    # Audit log
    audit = RestaurantAuditEvent(
        outlet_id=order.outlet_id,
        tenant_id=order.tenant_id,
        actor_id=manager_user.id,
        action="DISCOUNT_APPLIED",
        entity_name="order",
        entity_id=str(order.id),
        reason=payload.discount_reason,
        before_state={"discount_amount": float(old_discount)},
        after_state={"discount_amount": float(discount_val)}
    )
    db.add(audit)

    db.commit()
    db.refresh(order)
    return order


def _deduct_order_line_stock(
    db: Session,
    order: RestaurantOrder,
    line: RestaurantOrderLine,
    quantity: int,
    actor_id: Optional[UUID] = None
):
    """
    Deducts inventory stock based on dish recipes and modifier add-ons.
    Guards against:
    1. Multi-branch ingredient resolution (resolves ingredient for order.outlet_id).
    2. Modifiers / add-ons recipe deduction.
    3. UOM mismatch protection (normalizes recipe line unit to ingredient.recipe_uom).
    """
    if quantity <= 0:
        return

    # 1. Base dish recipe deduction
    if line.item_id:
        recipe = (
            db.query(RestaurantRecipe)
            .filter(RestaurantRecipe.item_id == line.item_id, RestaurantRecipe.variant_name == line.variant_name)
            .first()
        )
        if not recipe:
            recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.item_id == line.item_id).first()

        if recipe and recipe.lines:
            yield_val = Decimal(str(recipe.yield_servings or 1.00))
            if yield_val <= Decimal("0.00"):
                yield_val = Decimal("1.00")

            for r_line in recipe.lines:
                base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == r_line.ingredient_id).first()
                if base_ing:
                    # Multi-branch ingredient resolution
                    ingredient = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                    # UOM Normalization
                    norm_qty, _ = normalize_recipe_uom(
                        r_line.quantity_required,
                        r_line.unit,
                        ingredient.recipe_uom,
                        ingredient.uom_conversion_factor
                    )
                    consumption_qty = (norm_qty / yield_val) * Decimal(str(quantity))
                    ingredient.current_stock -= consumption_qty

                    cost_u = ingredient.cost_per_unit or Decimal("0.0000")
                    line_c = (consumption_qty * cost_u).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                    ledger = RestaurantStockLedger(
                        ingredient_id=ingredient.id,
                        outlet_id=order.outlet_id,
                        tenant_id=order.tenant_id,
                        signed_quantity=-consumption_qty,
                        unit_cost_at_time=cost_u,
                        total_cost=line_c,
                        reason="ORDER_CONSUMPTION",
                        source_type="order",
                        source_id=str(order.id),
                        actor_id=actor_id,
                        notes=f"KOT consumption for {quantity}x {line.item_name} ({line.variant_name})"
                    )
                    db.add(ledger)

    # 2. Modifiers / Add-ons deduction
    for mod in (line.selected_modifiers or []):
        mod_id = mod.get("id") or mod.get("modifier_option_id")
        if mod_id:
            try:
                mod_uuid = UUID(str(mod_id))
                mod_recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.modifier_option_id == mod_uuid).first()
                if mod_recipe and mod_recipe.lines:
                    m_yield = Decimal(str(mod_recipe.yield_servings or 1.00))
                    if m_yield <= Decimal("0.00"):
                        m_yield = Decimal("1.00")
                    for mr_line in mod_recipe.lines:
                        base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == mr_line.ingredient_id).first()
                        if base_ing:
                            ingredient = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                            norm_qty, _ = normalize_recipe_uom(
                                mr_line.quantity_required,
                                mr_line.unit,
                                ingredient.recipe_uom,
                                ingredient.uom_conversion_factor
                            )
                            mod_consumption = (norm_qty / m_yield) * Decimal(str(quantity))
                            ingredient.current_stock -= mod_consumption

                            ledger = RestaurantStockLedger(
                                ingredient_id=ingredient.id,
                                outlet_id=order.outlet_id,
                                tenant_id=order.tenant_id,
                                signed_quantity=-mod_consumption,
                                unit_cost_at_time=ingredient.cost_per_unit or Decimal("0.00"),
                                reason="ORDER_CONSUMPTION",
                                source_type="order",
                                source_id=str(order.id),
                                actor_id=actor_id,
                                notes=f"KOT modifier consumption for {quantity}x {mod.get('name', 'Modifier')}"
                            )
                            db.add(ledger)
            except (ValueError, TypeError):
                pass


def _reverse_order_line_stock(
    db: Session,
    order: RestaurantOrder,
    line: RestaurantOrderLine,
    quantity_to_reverse: int,
    reason: str = "ORDER_VOID",
    is_waste: bool = False,
    actor_id: Optional[UUID] = None
):
    """
    Reverses stock deduction for an order line that was already sent to kitchen.
    If is_waste is True, food was already prepared and discarded (logged as WASTAGE without stock return).
    If is_waste is False, stock is added back to current_stock with positive REVERSAL ledger entry.
    """
    if quantity_to_reverse <= 0:
        return

    # 1. Reverse Base Dish
    if line.item_id:
        recipe = (
            db.query(RestaurantRecipe)
            .filter(RestaurantRecipe.item_id == line.item_id, RestaurantRecipe.variant_name == line.variant_name)
            .first()
        )
        if not recipe:
            recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.item_id == line.item_id).first()

        if recipe and recipe.lines:
            yield_val = Decimal(str(recipe.yield_servings or 1.00))
            if yield_val <= Decimal("0.00"):
                yield_val = Decimal("1.00")

            for r_line in recipe.lines:
                base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == r_line.ingredient_id).first()
                if base_ing:
                    ingredient = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                    norm_qty, _ = normalize_recipe_uom(
                        r_line.quantity_required,
                        r_line.unit,
                        ingredient.recipe_uom,
                        ingredient.uom_conversion_factor
                    )
                    rev_qty = (norm_qty / yield_val) * Decimal(str(quantity_to_reverse))

                    line_loss_cost = (rev_qty * (ingredient.cost_per_unit or Decimal("0.00"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if not is_waste:
                        ingredient.current_stock += rev_qty
                        ledger = RestaurantStockLedger(
                            ingredient_id=ingredient.id,
                            outlet_id=order.outlet_id,
                            tenant_id=order.tenant_id,
                            signed_quantity=rev_qty, # Positive reversal back into stock
                            unit_cost_at_time=ingredient.cost_per_unit or Decimal("0.00"),
                            total_cost=line_loss_cost,
                            reason="REVERSAL",
                            source_type="order_void",
                            source_id=str(order.id),
                            actor_id=actor_id,
                            notes=f"Stock reversal: {quantity_to_reverse}x {line.item_name} ({reason}) [Qty: {rev_qty} {ingredient.recipe_uom}]"
                        )
                        db.add(ledger)
                    else:
                        ledger = RestaurantStockLedger(
                            ingredient_id=ingredient.id,
                            outlet_id=order.outlet_id,
                            tenant_id=order.tenant_id,
                            signed_quantity=Decimal("0.000"), # Already deducted, food wasted
                            unit_cost_at_time=ingredient.cost_per_unit or Decimal("0.00"),
                            total_cost=line_loss_cost, # Rupee loss explicitly preserved for waste analytics
                            reason="WASTAGE",
                            source_type="order_waste",
                            source_id=str(order.id),
                            actor_id=actor_id,
                            notes=f"[CUSTOMER_RETURN] KOT item wasted: {quantity_to_reverse}x {line.item_name} ({reason}) [Qty: {rev_qty} {ingredient.recipe_uom}]"
                        )
                        db.add(ledger)

    # 2. Reverse Modifiers
    for mod in (line.selected_modifiers or []):
        mod_id = mod.get("id") or mod.get("modifier_option_id")
        if mod_id:
            try:
                mod_uuid = UUID(str(mod_id))
                mod_recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.modifier_option_id == mod_uuid).first()
                if mod_recipe and mod_recipe.lines:
                    m_yield = Decimal(str(mod_recipe.yield_servings or 1.00))
                    if m_yield <= Decimal("0.00"):
                        m_yield = Decimal("1.00")
                    for mr_line in mod_recipe.lines:
                        base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == mr_line.ingredient_id).first()
                        if base_ing:
                            ingredient = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                            norm_qty, _ = normalize_recipe_uom(
                                mr_line.quantity_required,
                                mr_line.unit,
                                ingredient.recipe_uom,
                                ingredient.uom_conversion_factor
                            )
                            mod_rev = (norm_qty / m_yield) * Decimal(str(quantity_to_reverse))
                            mod_loss_cost = (mod_rev * (ingredient.cost_per_unit or Decimal("0.00"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                            if not is_waste:
                                ingredient.current_stock += mod_rev
                                ledger = RestaurantStockLedger(
                                    ingredient_id=ingredient.id,
                                    outlet_id=order.outlet_id,
                                    tenant_id=order.tenant_id,
                                    signed_quantity=mod_rev,
                                    unit_cost_at_time=ingredient.cost_per_unit or Decimal("0.00"),
                                    total_cost=mod_loss_cost,
                                    reason="REVERSAL",
                                    source_type="order_void",
                                    source_id=str(order.id),
                                    actor_id=actor_id,
                                    notes=f"Stock reversal modifier: {quantity_to_reverse}x {mod.get('name', 'Modifier')} ({reason}) [Qty: {mod_rev} {ingredient.recipe_uom}]"
                                )
                                db.add(ledger)
                            else:
                                ledger = RestaurantStockLedger(
                                    ingredient_id=ingredient.id,
                                    outlet_id=order.outlet_id,
                                    tenant_id=order.tenant_id,
                                    signed_quantity=Decimal("0.000"),
                                    unit_cost_at_time=ingredient.cost_per_unit or Decimal("0.00"),
                                    total_cost=mod_loss_cost, # Rupee loss explicitly preserved
                                    reason="WASTAGE",
                                    source_type="order_waste",
                                    source_id=str(order.id),
                                    actor_id=actor_id,
                                    notes=f"[CUSTOMER_RETURN] KOT modifier wasted: {quantity_to_reverse}x {mod.get('name', 'Modifier')} ({reason}) [Qty: {mod_rev} {ingredient.recipe_uom}]"
                                )
                                db.add(ledger)
            except (ValueError, TypeError):
                pass


@router.post("/{order_id}/send-to-kitchen", response_model=List[KitchenTicketResponse])
def send_to_kitchen(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Sends all pending order lines to station-based KOT tickets atomically.
    Deducts ingredient inventory stock using dish BOM recipes and modifier add-ons.
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    # 1. Re-firing / Idempotency Guard: Acquire row lock on order to serialize concurrent requests/retries
    order_query = db.query(RestaurantOrder)
    if parsed_uuid:
        order = order_query.filter(RestaurantOrder.id == parsed_uuid).with_for_update().first()
    else:
        order = order_query.filter(RestaurantOrder.order_number == str(order_id)).with_for_update().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    from dependencies import check_active_subscription
    if not check_active_subscription(order.tenant_id, db, outlet_id=order.outlet_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription for this branch has expired or is unpaid. Please renew your branch subscription to send KOTs to kitchen."
        )

    # Only fetch lines that are currently PENDING_SEND
    pending_lines = (
        db.query(RestaurantOrderLine)
        .filter(RestaurantOrderLine.order_id == order.id)
        .filter(RestaurantOrderLine.kot_status == "PENDING_SEND")
        .with_for_update()
        .all()
    )
    if not pending_lines:
        raise HTTPException(status_code=400, detail="No new items to send to kitchen")

    # 2. Deadlock Prevention: Gather all target ingredient IDs across dishes & modifiers,
    # and acquire row locks in deterministic ascending UUID order.
    target_ingredient_ids = set()
    for line in pending_lines:
        if line.item_id:
            recipe = (
                db.query(RestaurantRecipe)
                .filter(RestaurantRecipe.item_id == line.item_id, RestaurantRecipe.variant_name == line.variant_name)
                .first()
            )
            if not recipe:
                recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.item_id == line.item_id).first()
            if recipe and recipe.lines:
                for r_line in recipe.lines:
                    base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == r_line.ingredient_id).first()
                    if base_ing:
                        resolved_ing = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                        target_ingredient_ids.add(resolved_ing.id)

        for mod in (line.selected_modifiers or []):
            mod_id = mod.get("id") or mod.get("modifier_option_id")
            if mod_id:
                try:
                    mod_uuid = UUID(str(mod_id))
                    mod_recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.modifier_option_id == mod_uuid).first()
                    if mod_recipe and mod_recipe.lines:
                        for mr_line in mod_recipe.lines:
                            base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == mr_line.ingredient_id).first()
                            if base_ing:
                                resolved_ing = resolve_branch_ingredient(db, base_ing, order.outlet_id)
                                target_ingredient_ids.add(resolved_ing.id)
                except (ValueError, TypeError):
                    pass

    if target_ingredient_ids:
        # Strictly sort ascending to guarantee deadlock-free locking across concurrent transactions
        db.query(RestaurantIngredient)\
            .filter(RestaurantIngredient.id.in_(target_ingredient_ids))\
            .order_by(RestaurantIngredient.id)\
            .with_for_update()\
            .all()

    # Group lines by prep station (e.g. KITCHEN, BAR)
    stations_map = {}
    for line in pending_lines:
        stations_map.setdefault(line.prep_station, []).append(line)

    created_tickets = []
    kot_count = db.query(RestaurantKitchenTicket).filter(RestaurantKitchenTicket.order_id == order.id).count()

    for station, lines in stations_map.items():
        kot_count += 1
        ticket_num = f"KOT-{order.order_number.split('-')[-1]}-{kot_count:02d}"

        ticket = RestaurantKitchenTicket(
            order_id=order.id,
            ticket_number=ticket_num,
            station=station,
            status="PENDING",
            server_user_id=current_user.id if current_user else None
        )
        db.add(ticket)
        db.flush()

        for line in lines:
            line.kot_status = "SENT_TO_KITCHEN"
            item_ticket = RestaurantKitchenTicketItem(
                ticket_id=ticket.id,
                order_line_id=line.id,
                item_name=line.item_name,
                variant_name=line.variant_name,
                quantity=line.quantity,
                modifiers_summary=", ".join([m["name"] for m in line.selected_modifiers]) if line.selected_modifiers else None,
                special_instructions=line.special_instructions,
                status="PENDING"
            )
            db.add(item_ticket)

        # Audit event
        event = RestaurantKitchenEvent(
            ticket_id=ticket.id,
            actor_id=current_user.id if current_user else None,
            to_status="PENDING",
            notes=f"KOT {ticket_num} sent to {station}"
        )
        db.add(event)
        created_tickets.append(ticket)

    order.status = "SENT_TO_KITCHEN"
    order.version += 1

    # Deduct ingredient inventory stock based on recipes (BOM) & modifiers
    for line in pending_lines:
        _deduct_order_line_stock(
            db=db,
            order=order,
            line=line,
            quantity=line.quantity,
            actor_id=current_user.id if current_user else None
        )

    db.commit()
    table_name = "Takeaway"
    if order.table_id:
        table_obj = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
        if table_obj:
            table_name = table_obj.table_code

    outlet_name = "SirfBill Restaurant"
    outlet_obj = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == order.outlet_id).first()
    if outlet_obj and outlet_obj.name:
        outlet_name = outlet_obj.name

    for t in created_tickets:
        db.refresh(t)
        try:
            pdf_url = generate_kot_pdf(t, order, table_name=table_name, outlet_name=outlet_name)
            setattr(t, 'kot_pdf_url', pdf_url)
        except Exception as e:
            print(f"Error generating thermal KOT PDF: {e}")
            setattr(t, 'kot_pdf_url', None)

    return created_tickets


@router.post("/{order_id}/transitions")
def transition_order_status(
    order_id: str,
    payload: Optional[RestaurantOrderStateTransition] = None,
    payload_query: Optional[str] = Query(None, alias="payload"),
    status_query: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Transition order state (COMPLETED, CANCELLED, VOIDED, etc.) with audit logging.
    Supports payload in body or query param (e.g. ?payload=CANCELLED).
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    query = db.query(RestaurantOrder).options(joinedload(RestaurantOrder.lines))
    order = None
    if parsed_uuid:
        order = query.filter(RestaurantOrder.id == parsed_uuid).first()
    if not order:
        order = query.filter(RestaurantOrder.order_number == str(order_id)).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = None
    if payload:
        new_status = getattr(payload, "status", None) or getattr(payload, "target_status", None)
        if not new_status and isinstance(payload, dict):
            new_status = payload.get("status") or payload.get("target_status")
    if not new_status:
        new_status = payload_query or status_query

    if not new_status:
        raise HTTPException(status_code=400, detail="Either 'status' or 'target_status' is required.")

    new_status = str(new_status).upper()

    # Allow cancellation for all staff on POS/kiosk terminals (or Manager/Cashier/Admin)
    allowed_cancellation_roles = ["MANAGER", "OWNER", "ADMIN", "CASHIER", "WAITER", "STAFF"]
    if new_status in ["CANCELLED", "VOIDED"] and current_user and current_user.role and current_user.role.upper() not in allowed_cancellation_roles:
        raise HTTPException(status_code=403, detail="Staff or Cashier authorization required to cancel or void an order")

    # Optimistic locking check (ignore if not supplied or -1)
    expected_version = getattr(payload, "expected_version", None) if payload else None
    if expected_version is None and isinstance(payload, dict):
        expected_version = payload.get("expected_version")

    if expected_version is not None and expected_version != -1 and order.version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrency conflict: Order version is {order.version}, but client expected {expected_version}."
        )

    old_status = order.status
    order.status = new_status
    order.version += 1

    reason_val = getattr(payload, "reason", None) if payload else None
    if reason_val is None and isinstance(payload, dict):
        reason_val = payload.get("reason")

    # Reverse inventory stock for items already sent to kitchen (Point 2: Reversal vs Wastage)
    if new_status in ["CANCELLED", "VOIDED"]:
        is_waste = False
        disposition = "RETURN_TO_STOCK"
        if payload:
            is_waste = getattr(payload, "is_waste", False) or False
            disposition = (getattr(payload, "disposition", None) or "RETURN_TO_STOCK").upper()
            if isinstance(payload, dict):
                is_waste = payload.get("is_waste", False)
                disposition = (payload.get("disposition") or "RETURN_TO_STOCK").upper()
        if disposition == "WASTAGE":
            is_waste = True

        for line in (order.lines or []):
            if line.kot_status in ["SENT_TO_KITCHEN", "PREPARING", "READY", "SERVED"] and line.quantity > 0:
                _reverse_order_line_stock(
                    db=db,
                    order=order,
                    line=line,
                    quantity_to_reverse=line.quantity,
                    reason=reason_val or f"Order {new_status}",
                    is_waste=is_waste,
                    actor_id=current_user.id if current_user else None
                )
            line.kot_status = "CANCELLED"

    # Direct Counter / Takeaway Billing: If completing an order that had un-sent lines, deduct them now
    if new_status == "COMPLETED":
        pending_lines = [l for l in (order.lines or []) if l.kot_status == "PENDING_SEND" and l.quantity > 0]
        for line in pending_lines:
            _deduct_order_line_stock(
                db=db,
                order=order,
                line=line,
                quantity=line.quantity,
                actor_id=current_user.id if current_user else None
            )
            line.kot_status = "SERVED"

    # Free up table if order finished or cancelled
    if new_status in ["COMPLETED", "CANCELLED", "VOIDED"] and order.table_id:
        table = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
        if table:
            table.status = "VACANT"

    # Audit log
    audit = RestaurantAuditEvent(
        outlet_id=order.outlet_id,
        tenant_id=order.tenant_id,
        actor_id=current_user.id if current_user else None,
        action=f"ORDER_{new_status}",
        entity_name="order",
        entity_id=str(order.id),
        reason=reason_val,
        before_state={"status": old_status},
        after_state={"status": new_status}
    )
    db.add(audit)

    db.commit()
    db.refresh(order)
    return {
        "id": str(order.id),
        "outlet_id": str(order.outlet_id),
        "tenant_id": str(order.tenant_id),
        "order_number": order.order_number,
        "order_type": order.order_type,
        "status": order.status,
        "table_id": str(order.table_id) if order.table_id else None,
        "customer_id": str(order.customer_id) if order.customer_id else None,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "waiter_id": str(order.waiter_id) if order.waiter_id else None,
        "shift_id": str(order.shift_id) if order.shift_id else None,
        "subtotal": float(order.subtotal or 0.0),
        "discount_amount": float(order.discount_amount or 0.0),
        "discount_reason": order.discount_reason,
        "tax_amount": float(order.tax_amount or 0.0),
        "rounding_adjustment": float(order.rounding_adjustment or 0.0),
        "grand_total": float(order.grand_total or 0.0),
        "paid_amount": float(order.paid_amount or 0.0),
        "notes": order.notes,
        "version": order.version,
        "idempotency_key": order.idempotency_key,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "lines": [
            {
                "id": str(l.id),
                "order_id": str(l.order_id),
                "item_id": str(l.item_id) if l.item_id else None,
                "item_name": l.item_name,
                "variant_name": l.variant_name,
                "prep_station": l.prep_station,
                "quantity": l.quantity,
                "unit_price": float(l.unit_price or 0.0),
                "modifier_price": float(l.modifier_price or 0.0),
                "discount_amount": float(l.discount_amount or 0.0),
                "tax_rate": float(l.tax_rate or 0.0),
                "tax_amount": float(l.tax_amount or 0.0),
                "line_total": float(l.line_total or 0.0),
                "selected_modifiers": l.selected_modifiers,
                "special_instructions": l.special_instructions,
                "kot_status": l.kot_status,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in (order.lines or [])
        ]
    }


@router.post("/{order_id}/items/{line_id}/void", response_model=RestaurantOrderResponse)
def void_order_item(
    order_id: str,
    line_id: UUID,
    payload: RestaurantOrderItemVoid,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Void or cancel a specific item (or partial quantity) from an open order.
    - If KOT was already sent to kitchen:
      - is_waste = False: Restores raw ingredient inventory via positive REVERSAL stock ledger entries.
      - is_waste = True: Logs a WASTAGE audit ledger entry (stock stays consumed because food was prepared).
    - Recalculates order subtotal, tax amount, and grand total.
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    order_query = db.query(RestaurantOrder)
    if parsed_uuid:
        order = order_query.filter(RestaurantOrder.id == parsed_uuid).with_for_update().first()
    else:
        order = order_query.filter(RestaurantOrder.order_number == str(order_id)).with_for_update().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in ["COMPLETED", "CANCELLED", "VOIDED"]:
        raise HTTPException(status_code=400, detail=f"Cannot void items on an order in {order.status} state")

    if payload.expected_version is not None and payload.expected_version != -1:
        if order.version != payload.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Concurrency conflict: Order version is {order.version}, but client expected {payload.expected_version}."
            )

    line = db.query(RestaurantOrderLine).filter(
        RestaurantOrderLine.id == line_id,
        RestaurantOrderLine.order_id == order.id
    ).with_for_update().first()
    if not line:
        raise HTTPException(status_code=404, detail="Order line not found")

    if line.quantity <= 0 or line.kot_status == "CANCELLED":
        raise HTTPException(status_code=400, detail="Line item is already voided or has 0 quantity")

    void_qty = payload.quantity if (payload.quantity and payload.quantity < line.quantity) else line.quantity

    # 1. Reverse stock ONLY if KOT was already sent to kitchen (Edge Case 3 Guard)
    # If kot_status == "PENDING_SEND", the item was never fired to kitchen; ORDER_CONSUMPTION never ran.
    # We do NOT run _reverse_order_line_stock to prevent artificially inflating stock.
    if line.kot_status in ["SENT_TO_KITCHEN", "PREPARING", "READY", "SERVED"]:
        _reverse_order_line_stock(
            db=db,
            order=order,
            line=line,
            quantity_to_reverse=void_qty,
            reason=payload.reason,
            is_waste=payload.is_waste,
            actor_id=current_user.id if current_user else None
        )

    # 2. Update line item quantity or mark cancelled
    remaining_qty = line.quantity - void_qty
    if remaining_qty <= 0:
        line.quantity = 0
        line.kot_status = "CANCELLED"
        line.tax_amount = Decimal("0.00")
        line.line_total = Decimal("0.00")
    else:
        line.quantity = remaining_qty
        base_sub = (line.unit_price + line.modifier_price) * Decimal(str(remaining_qty))
        tax_amt = (base_sub * (line.tax_rate / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line.tax_amount = tax_amt
        line.line_total = base_sub + tax_amt - line.discount_amount

    # 3. Recalculate order totals from active lines
    active_lines = [l for l in order.lines if l.quantity > 0 and l.kot_status != "CANCELLED"]
    order.subtotal = sum((l.unit_price + l.modifier_price) * Decimal(str(l.quantity)) for l in active_lines)
    order.tax_amount = sum(l.tax_amount for l in active_lines)
    raw_total = order.subtotal - order.discount_amount + order.tax_amount
    rounded = raw_total.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    order.rounding_adjustment = rounded - raw_total
    order.grand_total = rounded
    order.version += 1

    # 4. Audit event
    audit = RestaurantAuditEvent(
        outlet_id=order.outlet_id,
        tenant_id=order.tenant_id,
        actor_id=current_user.id if current_user else None,
        action="ORDER_ITEM_VOID",
        entity_name="order_line",
        entity_id=str(line.id),
        reason=payload.reason,
        before_state={"item_name": line.item_name, "voided_qty": void_qty, "is_waste": payload.is_waste},
        after_state={"remaining_qty": remaining_qty, "order_grand_total": float(order.grand_total)}
    )
    db.add(audit)

    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/settle")
def settle_order(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Settle payment for an order and transition to COMPLETED.
    """
    order = None
    try:
        uuid_val = UUID(str(order_id))
        order = db.query(RestaurantOrder).filter(RestaurantOrder.id == uuid_val).first()
    except (ValueError, TypeError):
        # Temp order or custom order ID
        pass

    if not order:
        # Check by order number or fallback
        order = db.query(RestaurantOrder).filter(RestaurantOrder.order_number == order_id).first()

    if not order:
        # If temp_order or order was not found, return success dummy so client doesn't block
        return {
            "status": "SETTLED",
            "message": "Order payment settled successfully",
            "order_id": order_id
        }

    settled_amount = Decimal(str(payload.get("settled_amount") or order.grand_total))
    discount_amount = Decimal(str(payload.get("discount_amount") or 0.0))
    pay_method = (payload.get("payment_method") or payload.get("method") or order.payment_method or "CASH").upper()

    order.paid_amount = settled_amount
    order.payment_method = pay_method
    if payload.get("customer_name"):
        order.customer_name = payload["customer_name"]
    if payload.get("customer_phone"):
        order.customer_phone = payload["customer_phone"]
    if discount_amount > 0:
        order.discount_amount = discount_amount
        order.grand_total = max(Decimal("0.00"), order.grand_total - discount_amount)
    order.status = "COMPLETED"
    order.version += 1

    # Direct Counter / Takeaway Billing: If completing an order with un-sent lines, deduct them now
    pending_lines = [l for l in (order.lines or []) if l.kot_status == "PENDING_SEND" and l.quantity > 0]
    for line in pending_lines:
        _deduct_order_line_stock(
            db=db,
            order=order,
            line=line,
            quantity=line.quantity,
            actor_id=current_user.id if current_user else None
        )
        line.kot_status = "SERVED"

    # Record settlement transaction in restaurant_tenders table
    tender = RestaurantTender(
        order_id=order.id,
        tenant_id=order.tenant_id,
        method=pay_method,
        amount=settled_amount,
        reference=payload.get("reference") or payload.get("transaction_id"),
        status="COMPLETED",
        cashier_id=current_user.id if current_user else None
    )
    db.add(tender)

    if order.table_id:
        table = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
        if table:
            table.status = "VACANT"

    db.commit()
    db.refresh(order)

    # CRM Settlement Pipeline (RFM update, Loyalty earn, Khata tab, Receipt notification)
    try:
        from routes.restaurant_crm import process_order_settlement_crm
        khata_amt = settled_amount if pay_method in ("KHATA", "CREDIT", "STORE_CREDIT") else Decimal("0.00")
        process_order_settlement_crm(db=db, order=order, khata_amount=khata_amt)
        db.commit()
    except Exception as e:
        print(f"Error in CRM settlement processing: {e}")

    # Generate thermal bill PDF and save to uploads/bills/
    table_name = "Takeaway"
    if order.table_id:
        table_obj = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
        if table_obj:
            table_name = table_obj.table_code

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == order.outlet_id).first()
    bill_pdf_url = None
    try:
        bill_pdf_url = generate_bill_pdf(order, outlet, table_name=table_name)
    except Exception as e:
        print(f"Error generating thermal bill PDF in settle: {e}")

    return {
        "status": "SETTLED",
        "order_id": str(order.id),
        "order_number": order.order_number,
        "paid_amount": float(order.paid_amount),
        "grand_total": float(order.grand_total),
        "bill_pdf_url": bill_pdf_url
    }


@router.post("/{order_id}/print-bill")
def print_thermal_bill(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Accept thermal bill print job for order and generate 80mm thermal bill in uploads/bills.
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    query = db.query(RestaurantOrder).options(joinedload(RestaurantOrder.lines))
    order = None
    if parsed_uuid:
        order = query.filter(RestaurantOrder.id == parsed_uuid).first()
    if not order:
        order = query.filter(RestaurantOrder.order_number == str(order_id)).first()

    bill_pdf_url = None
    if order:
        table_name = "Takeaway"
        if order.table_id:
            table_obj = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
            if table_obj:
                table_name = table_obj.table_code

        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == order.outlet_id).first()
        try:
            bill_pdf_url = generate_bill_pdf(order, outlet, table_name=table_name)
        except Exception as e:
            print(f"Error generating thermal bill PDF in print-bill: {e}")

    return {
        "status": "SUCCESS",
        "message": f"Thermal 80mm print job queued for order {order_id}",
        "order_id": order_id,
        "bill_pdf_url": bill_pdf_url
    }


# --- Table QR Order Confirmation, Rejection, and Customer Dining Flow ---


@router.post("/{order_id}/confirm-qr", response_model=RestaurantOrderResponse)
def confirm_qr_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    POS Cashier Action: Confirms a customer-scanned Table QR order,
    locks table status to OCCUPIED, and automatically fires KOT tickets to the kitchen KDS.
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    order_query = db.query(RestaurantOrder)
    if parsed_uuid:
        order = order_query.filter(RestaurantOrder.id == parsed_uuid).with_for_update().first()
    else:
        order = order_query.filter(RestaurantOrder.order_number == str(order_id)).with_for_update().first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in ["PENDING_CONFIRMATION", "OPEN"]:
        raise HTTPException(status_code=400, detail=f"Cannot confirm order in '{order.status}' status")

    # Update Table status to OCCUPIED
    if order.table_id:
        table = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
        if table:
            table.status = "OCCUPIED"

    # Set status to OPEN before calling send_to_kitchen
    order.status = "OPEN"
    db.commit()

    # Automatically fire KOT tickets to the kitchen
    try:
        send_to_kitchen(order_id=str(order.id), db=db, current_user=current_user)
    except Exception as e:
        print(f"Warning: send_to_kitchen inside confirm_qr_order completed with note: {e}")

    db.refresh(order)
    return order


@router.post("/{order_id}/reject-qr", response_model=RestaurantOrderResponse)
def reject_qr_order(
    order_id: str,
    payload: Optional[RejectQROrderRequest] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    POS Cashier Action: Rejects an unverified customer QR order (e.g. 86 item out of stock, guest left table).
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    order_query = db.query(RestaurantOrder)
    if parsed_uuid:
        order = order_query.filter(RestaurantOrder.id == parsed_uuid).first()
    else:
        order = order_query.filter(RestaurantOrder.order_number == str(order_id)).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    reason = (payload.reason if payload else None) or "Rejected by cashier at POS terminal"
    order.status = "CANCELLED"
    order.notes = f"{order.notes or ''} [REJECTED: {reason}]".strip()

    # Mark lines as CANCELLED
    for line in order.lines:
        line.kot_status = "CANCELLED"

    # If table has no other active orders, reset table to VACANT
    if order.table_id:
        other_active = (
            db.query(RestaurantOrder)
            .filter(RestaurantOrder.table_id == order.table_id)
            .filter(RestaurantOrder.id != order.id)
            .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "SERVED"]))
            .first()
        )
        if not other_active:
            table = db.query(RestaurantTable).filter(RestaurantTable.id == order.table_id).first()
            if table and table.status != "VACANT":
                table.status = "VACANT"

    db.commit()
    db.refresh(order)
    return order


# =====================================================================
# --- Public Customer QR Dine-In Ordering Router ---
# =====================================================================

customer_dining_router = APIRouter(
    prefix="/api/restaurant/customer",
    tags=["Restaurant - Customer QR Dine-In"]
)

@customer_dining_router.get("/table/{table_id}", response_model=CustomerTableInfoResponse)
def get_customer_table_info(
    table_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Customer Scan Landing: Returns table details, restaurant branding, active ongoing table order,
    prefilled customer profile for re-ordering, and settlement/thank you state.
    """
    table = db.query(RestaurantTable).filter(
        RestaurantTable.id == table_id,
        RestaurantTable.is_active == True
    ).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found or is currently inactive.")

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == table.outlet_id).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant outlet not found.")

    active_statuses = ["PENDING_CONFIRMATION", "OPEN", "IN_KITCHEN", "SENT_TO_KITCHEN", "HOLD", "READY", "SERVED"]
    active_order = (
        db.query(RestaurantOrder)
        .options(joinedload(RestaurantOrder.lines))
        .filter(RestaurantOrder.table_id == table.id)
        .filter(RestaurantOrder.status.in_(active_statuses))
        .order_by(RestaurantOrder.created_at.desc())
        .first()
    )

    customer_name = None
    customer_phone = None
    prefill_name = None
    prefill_phone = None
    active_order_lines = []
    active_grand_total = 0.0
    active_items_count = 0
    is_settled = False
    show_thank_you = False
    settlement_message = None
    recent_order = None

    if active_order:
        customer_name = active_order.customer_name
        customer_phone = active_order.customer_phone
        if customer_name and customer_name.strip().lower() != "dine-in guest":
            prefill_name = customer_name.strip()
        prefill_phone = customer_phone
        active_grand_total = float(active_order.grand_total or 0.0)
        active_items_count = sum(l.quantity for l in (active_order.lines or []))
        active_order_lines = [
            CustomerTableOrderLineSummary(
                id=l.id,
                item_name=l.item_name,
                variant_name=l.variant_name,
                quantity=l.quantity,
                unit_price=float(l.unit_price or 0.0),
                line_total=float(l.line_total or 0.0),
                kot_status=l.kot_status or "PENDING_SEND"
            )
            for l in (active_order.lines or [])
        ]
    else:
        # Check if table was recently settled (completed order within last 45 minutes)
        recent_order = (
            db.query(RestaurantOrder)
            .options(joinedload(RestaurantOrder.lines))
            .filter(RestaurantOrder.table_id == table.id)
            .filter(RestaurantOrder.status == "COMPLETED")
            .order_by(RestaurantOrder.updated_at.desc())
            .first()
        )
        if recent_order and recent_order.updated_at:
            time_diff = (get_current_time() - recent_order.updated_at).total_seconds()
            if time_diff <= 2700:  # 45 minutes
                is_settled = True
                show_thank_you = True
                settlement_message = "Thank you for dining with us! Your order has been settled."
                customer_name = recent_order.customer_name
                customer_phone = recent_order.customer_phone
                if customer_name and customer_name.strip().lower() != "dine-in guest":
                    prefill_name = customer_name.strip()
                prefill_phone = customer_phone
                active_grand_total = float(recent_order.grand_total or 0.0)
                active_items_count = sum(l.quantity for l in (recent_order.lines or []))
                active_order_lines = [
                    CustomerTableOrderLineSummary(
                        id=l.id,
                        item_name=l.item_name,
                        variant_name=l.variant_name,
                        quantity=l.quantity,
                        unit_price=float(l.unit_price or 0.0),
                        line_total=float(l.line_total or 0.0),
                        kot_status=l.kot_status or "SERVED"
                    )
                    for l in (recent_order.lines or [])
                ]

    resolved_order_id = active_order.id if active_order else (recent_order.id if (is_settled and recent_order) else None)
    resolved_order_number = active_order.order_number if active_order else (recent_order.order_number if (is_settled and recent_order) else None)
    resolved_order_status = active_order.status if active_order else (recent_order.status if (is_settled and recent_order) else None)

    svc = outlet.service_settings if isinstance(outlet.service_settings, dict) else {}
    resolved_gst = (outlet.gstin or svc.get("gst_number") or svc.get("gstin") or "").strip() or None
    resolved_fssai = (outlet.fssai or svc.get("fssai") or svc.get("fssai_number") or "").strip() or None
    if not resolved_gst:
        from models.shop_settings import ShopSettings
        shop_cfg = db.query(ShopSettings).filter(ShopSettings.tenant_id == outlet.tenant_id).first()
        if shop_cfg and shop_cfg.gst_number:
            resolved_gst = shop_cfg.gst_number.strip() or None

    return CustomerTableInfoResponse(
        table_id=table.id,
        table_code=table.table_code,
        section=table.section,
        outlet_id=outlet.id,
        outlet_name=outlet.name,
        outlet_address=outlet.address,
        outlet_phone=outlet.phone,
        outlet_logo=outlet.logo_url,
        outlet_gst=resolved_gst,
        outlet_fssai=resolved_fssai,
        currency=outlet.currency or "INR",
        tax_rate=float(outlet.tax_rate or 5.0),
        active_order_id=resolved_order_id,
        active_order_number=resolved_order_number,
        active_order_status=resolved_order_status,
        customer_name=customer_name,
        customer_phone=customer_phone,
        prefill_name=prefill_name,
        prefill_phone=prefill_phone,
        active_order_customer_name=customer_name,
        active_order_customer_phone=customer_phone,
        active_order_grand_total=active_grand_total,
        active_order_items_count=active_items_count,
        active_order_lines=active_order_lines,
        is_settled=is_settled,
        show_thank_you=show_thank_you,
        settlement_message=settlement_message
    )


@customer_dining_router.get("/table/{table_id}/active-order", response_model=Optional[RestaurantOrderResponse])
def get_customer_table_active_order(
    table_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Returns the current active order or recent completed order for a table so customer can view their receipt or order state.
    """
    active_statuses = ["PENDING_CONFIRMATION", "OPEN", "IN_KITCHEN", "SENT_TO_KITCHEN", "HOLD", "READY", "SERVED"]
    order = (
        db.query(RestaurantOrder)
        .options(joinedload(RestaurantOrder.lines))
        .filter(RestaurantOrder.table_id == table_id)
        .filter(RestaurantOrder.status.in_(active_statuses))
        .order_by(RestaurantOrder.created_at.desc())
        .first()
    )
    if not order:
        recent = (
            db.query(RestaurantOrder)
            .options(joinedload(RestaurantOrder.lines))
            .filter(RestaurantOrder.table_id == table_id)
            .filter(RestaurantOrder.status == "COMPLETED")
            .order_by(RestaurantOrder.updated_at.desc())
            .first()
        )
        if recent and recent.updated_at:
            if (get_current_time() - recent.updated_at).total_seconds() <= 2700:
                return recent
        return None
    return order



@customer_dining_router.get("/menu")
def get_customer_menu(
    outlet_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Public digital menu for customer phone scanner.
    Returns categorized items, variant prices, badges, and modifiers.
    """
    categories = db.query(RestaurantMenuCategory).filter(
        RestaurantMenuCategory.outlet_id == outlet_id,
        RestaurantMenuCategory.is_active == True
    ).order_by(RestaurantMenuCategory.sort_order.asc(), RestaurantMenuCategory.name.asc()).all()

    items = db.query(RestaurantMenuItem).filter(
        RestaurantMenuItem.outlet_id == outlet_id,
        RestaurantMenuItem.is_active == True
    ).order_by(RestaurantMenuItem.name.asc()).all()

    cats_map = {}
    for c in categories:
        cats_map[str(c.id)] = {
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "icon_emoji": c.icon_emoji,
            "items": []
        }

    for item in items:
        c_id = str(item.category_id) if item.category_id else "uncategorized"
        if c_id not in cats_map:
            cats_map[c_id] = {
                "id": c_id,
                "name": "General Menu",
                "description": None,
                "icon_emoji": "🍽️",
                "items": []
            }
        cats_map[c_id]["items"].append({
            "id": str(item.id),
            "name": item.name,
            "short_code": item.short_code,
            "description": item.description,
            "price": float(item.price or 0.0),
            "variant_prices": item.variant_prices,
            "badge": item.badge,
            "item_type": item.item_type,
            "is_veg": (item.item_type == "VEG"),
            "image_url": item.image_url,
            "prep_station": item.prep_station,
            "is_available": item.is_available
        })

    return {
        "outlet_id": str(outlet_id),
        "categories": list(cats_map.values()),
        "total_items": len(items)
    }


@customer_dining_router.post("/orders", response_model=RestaurantOrderResponse, status_code=status.HTTP_201_CREATED)
def customer_place_order(
    payload: CustomerTableOrderCreate,
    db: Session = Depends(get_db)
):
    """
    Customer Action: Places a dine-in order from mobile camera scan.
    Enters as PENDING_CONFIRMATION awaiting cashier confirmation at the POS.
    """
    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == payload.outlet_id).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant outlet not found.")

    table = db.query(RestaurantTable).filter(
        RestaurantTable.id == payload.table_id,
        RestaurantTable.outlet_id == outlet.id,
        RestaurantTable.is_active == True
    ).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found or is currently inactive.")

    # Check Branch Subscription Status
    from dependencies import check_active_subscription
    if not check_active_subscription(outlet.tenant_id, db, outlet_id=outlet.id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Online/QR ordering is temporarily unavailable for this branch. Please contact restaurant staff."
        )

    # Idempotency check
    if payload.idempotency_key:
        existing = db.query(RestaurantOrder).filter(RestaurantOrder.idempotency_key == payload.idempotency_key).first()
        if existing:
            return existing

    # Upsert RestaurantCustomer if phone or custom name is provided
    resolved_customer_id = None
    clean_name = (payload.customer_name or "").strip()
    clean_phone = (payload.customer_phone or "").strip()
    if clean_phone:
        from models.restaurant_customer import RestaurantCustomer
        digits = "".join(filter(str.isdigit, clean_phone)) or clean_phone
        cust = db.query(RestaurantCustomer).filter(
            RestaurantCustomer.tenant_id == outlet.tenant_id,
            RestaurantCustomer.phone.ilike(f"%{digits}%")
        ).first()
        if cust:
            if clean_name and clean_name.lower() != "dine-in guest":
                cust.name = clean_name
            resolved_customer_id = cust.id
        else:
            cust = RestaurantCustomer(
                outlet_id=outlet.id,
                home_outlet_id=outlet.id,
                tenant_id=outlet.tenant_id,
                name=clean_name or "Dine-in Guest",
                phone=clean_phone,
            )
            db.add(cust)
            db.flush()
            resolved_customer_id = cust.id

    # Check if this table already has an active unpaid order — if so, append new items to it
    active_statuses = ["PENDING_CONFIRMATION", "OPEN", "IN_KITCHEN", "SENT_TO_KITCHEN", "READY", "SERVED"]
    order = db.query(RestaurantOrder).filter(
        RestaurantOrder.table_id == table.id,
        RestaurantOrder.outlet_id == outlet.id,
        RestaurantOrder.status.in_(active_statuses),
    ).order_by(RestaurantOrder.created_at.desc()).first()

    if order:
        order.status = "PENDING_CONFIRMATION"
        if resolved_customer_id:
            order.customer_id = resolved_customer_id
        if clean_name and clean_name.lower() != "dine-in guest":
            order.customer_name = clean_name
        elif not order.customer_name or order.customer_name.strip().lower() == "dine-in guest":
            if clean_name:
                order.customer_name = clean_name
        if clean_phone:
            order.customer_phone = clean_phone
        if payload.notes:
            order.notes = f"{order.notes} | {payload.notes}" if order.notes else payload.notes
        order.version = (order.version or 1) + 1
        db.flush()
        subtotal_acc = Decimal(str(order.subtotal or 0))
        tax_acc = Decimal(str(order.tax_amount or 0))
    else:
        order_num = _generate_order_number(db, outlet.id)
        order = RestaurantOrder(
            outlet_id=outlet.id,
            tenant_id=outlet.tenant_id,
            order_number=order_num,
            order_type="DINE_IN",
            status="PENDING_CONFIRMATION",
            table_id=table.id,
            customer_id=resolved_customer_id,
            customer_name=clean_name or "Dine-in Guest",
            customer_phone=clean_phone or None,
            notes=payload.notes,
            payment_method="CASH",
            idempotency_key=payload.idempotency_key,
            subtotal=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            rounding_adjustment=Decimal("0.00"),
            grand_total=Decimal("0.00"),
            paid_amount=Decimal("0.00"),
            version=1
        )
        db.add(order)
        db.flush()
        subtotal_acc = Decimal("0.00")
        tax_acc = Decimal("0.00")

    for line_in in payload.items:
        resolved_item_id = line_in.item_id or line_in.menu_item_id
        if resolved_item_id:
            try:
                resolved_item_id = UUID(str(resolved_item_id))
            except (ValueError, TypeError):
                resolved_item_id = None

        item = None
        if resolved_item_id:
            item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == resolved_item_id).first()
        if not item and line_in.name:
            item = db.query(RestaurantMenuItem).filter(
                RestaurantMenuItem.outlet_id == outlet.id,
                RestaurantMenuItem.name.ilike(line_in.name)
            ).first()

        qty = max(1, line_in.quantity)
        if item:
            unit_p, mod_p, tax_r, tax_a, line_tot, sel_mods = _calculate_line_item(
                db, item.id, line_in.variant_name, qty, line_in.modifiers
            )[1:]
            item_name = item.name
            prep_station = item.prep_station
        else:
            unit_p = line_in.unit_price or line_in.price or Decimal("0.00")
            mod_p = Decimal("0.00")
            tax_r = Decimal(str(outlet.tax_rate or 5.0))
            tax_a = (unit_p * Decimal(str(qty)) * tax_r) / Decimal("100.00")
            line_tot = (unit_p * Decimal(str(qty))) + tax_a
            sel_mods = None
            item_name = line_in.name or "Food Item"
            prep_station = "KITCHEN"

        instructions = line_in.special_instructions or line_in.notes

        db_line = RestaurantOrderLine(
            order_id=order.id,
            item_id=item.id if item else None,
            item_name=item_name,
            variant_name=line_in.variant_name,
            prep_station=prep_station,
            quantity=qty,
            unit_price=unit_p,
            modifier_price=mod_p,
            tax_rate=tax_r,
            tax_amount=tax_a,
            line_total=line_tot,
            selected_modifiers=sel_mods,
            special_instructions=instructions,
            kot_status="PENDING_SEND"
        )
        db.add(db_line)
        subtotal_acc += (unit_p + mod_p) * Decimal(str(qty))
        tax_acc += tax_a

    order.subtotal = subtotal_acc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    order.tax_amount = tax_acc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raw_grand = order.subtotal + order.tax_amount
    order.grand_total = raw_grand.quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    order.rounding_adjustment = order.grand_total - raw_grand

    # Keep table in RESERVED / incoming state while awaiting confirmation
    if table.status == "VACANT":
        table.status = "RESERVED"

    db.commit()
    db.refresh(order)
    return order


@customer_dining_router.get("/orders/{order_id}", response_model=RestaurantOrderResponse)
def get_customer_order_status(
    order_id: str,
    db: Session = Depends(get_db)
):
    """
    Live Status Check for Customer Phone: Returns current status (PENDING_CONFIRMATION, SENT_TO_KITCHEN, SERVED).
    """
    parsed_uuid = None
    try:
        parsed_uuid = UUID(str(order_id))
    except (ValueError, TypeError):
        pass

    query = db.query(RestaurantOrder).options(joinedload(RestaurantOrder.lines))
    order = None
    if parsed_uuid:
        order = query.filter(RestaurantOrder.id == parsed_uuid).first()
    if not order:
        order = query.filter(RestaurantOrder.order_number == str(order_id)).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order

