from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import datetime, date
import re
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session, joinedload

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_ingredient import RestaurantIngredient, RestaurantIngredientCategory
from models.restaurant_stock_ledger import RestaurantStockLedger
from models.restaurant_stock_transfer import RestaurantStockTransfer, RestaurantStockTransferItem
from schemas.restaurant_stock_transfer import (
    StockTransferCreate, StockTransferDispatchInput,
    StockTransferReceiveInput, StockTransferResponse, StockTransferItemResponse
)
from dependencies import get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff
from utils.timezone import get_current_time

router = APIRouter(
    prefix="/api/restaurant/inventory/transfers",
    tags=["Restaurant - Stock Transfers"]
)

def resolve_outlet(db: Session, outlet_id: Optional[UUID] = None) -> RestaurantOutlet:
    outlet = None
    if outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == outlet_id).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True).first()
    if not outlet:
        outlet = db.query(RestaurantOutlet).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Restaurant outlet/branch not found")
    return outlet

def generate_transfer_number(db: Session, tenant_id: UUID) -> str:
    """
    Generates a sequential transfer number per tenant for the current month: ST-YYYYMM-XXXX
    """
    now = get_current_time()
    prefix = f"ST-{now.strftime('%Y%m')}-"
    
    count = db.query(func.count(RestaurantStockTransfer.id)).filter(
        RestaurantStockTransfer.tenant_id == tenant_id,
        RestaurantStockTransfer.transfer_number.like(f"{prefix}%")
    ).scalar() or 0
    
    return f"{prefix}{(count + 1):04d}"

def map_transfer_to_response(transfer: RestaurantStockTransfer) -> StockTransferResponse:
    from_name = transfer.from_outlet.name if transfer.from_outlet else "Central Store"
    to_name = transfer.to_outlet.name if transfer.to_outlet else "Branch Outlet"
    
    from_loc = transfer.from_station or from_name
    to_loc = transfer.to_station or to_name

    transferred_by = "Staff"
    if transfer.initiated_by:
        transferred_by = transfer.initiated_by.name or transfer.initiated_by.username or "Staff"
    elif transfer.dispatched_by:
        transferred_by = transfer.dispatched_by.name or transfer.dispatched_by.username or "Staff"

    items_res = []
    for it in (transfer.items or []):
        items_res.append(StockTransferItemResponse(
            id=it.id,
            transfer_id=it.transfer_id,
            ingredient_id=it.ingredient_id,
            destination_ingredient_id=it.destination_ingredient_id,
            ingredient_name=it.ingredient_name,
            sku=it.sku,
            unit=it.unit,
            quantity_requested=it.quantity_requested,
            quantity_dispatched=it.quantity_dispatched,
            quantity_received=it.quantity_received,
            quantity_variance=it.quantity_variance,
            unit_cost=it.unit_cost,
            total_cost=it.total_cost,
            variance_reason=it.variance_reason,
            batch_number=it.batch_number,
            expiry_date=it.expiry_date.date() if it.expiry_date else None,
            created_at=it.created_at
        ))

    return StockTransferResponse(
        id=transfer.id,
        tenant_id=transfer.tenant_id,
        transfer_number=transfer.transfer_number,
        transfer_type=transfer.transfer_type,
        from_outlet_id=transfer.from_outlet_id,
        from_outlet_name=from_name,
        to_outlet_id=transfer.to_outlet_id,
        to_outlet_name=to_name,
        from_station=transfer.from_station,
        to_station=transfer.to_station,
        status=transfer.status,
        initiated_by_id=transfer.initiated_by_id,
        initiated_by_name=transfer.initiated_by.name if transfer.initiated_by else None,
        dispatched_by_id=transfer.dispatched_by_id,
        dispatched_by_name=transfer.dispatched_by.name if transfer.dispatched_by else None,
        received_by_id=transfer.received_by_id,
        received_by_name=transfer.received_by.name if transfer.received_by else None,
        dispatched_at=transfer.dispatched_at,
        received_at=transfer.received_at,
        vehicle_number=transfer.vehicle_number,
        driver_name=transfer.driver_name,
        driver_phone=transfer.driver_phone,
        sender_signature=transfer.sender_signature,
        driver_signature=transfer.driver_signature,
        receiver_signature=transfer.receiver_signature,
        total_items=transfer.total_items,
        total_valuation=transfer.total_valuation,
        notes=transfer.notes,
        created_at=transfer.created_at,
        updated_at=transfer.updated_at,
        items=items_res,
        from_location=from_loc,
        to_location=to_loc,
        transfer_date=transfer.created_at,
        transferred_by=transferred_by,
        total_items_count=transfer.total_items
    )


# ----------------- STOCK TRANSFER ENDPOINTS -----------------

@router.get("", response_model=List[StockTransferResponse])
def get_stock_transfers(
    outlet_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    transfer_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List stock transfers for an outlet (both outbound sent and inbound received).
    """
    query = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.to_outlet),
            joinedload(RestaurantStockTransfer.initiated_by),
            joinedload(RestaurantStockTransfer.dispatched_by),
            joinedload(RestaurantStockTransfer.received_by),
            joinedload(RestaurantStockTransfer.items)
        )
    )

    if outlet_id:
        query = query.filter(
            or_(
                RestaurantStockTransfer.from_outlet_id == outlet_id,
                RestaurantStockTransfer.to_outlet_id == outlet_id
            )
        )

    if status:
        query = query.filter(RestaurantStockTransfer.status == status.upper())

    if transfer_type:
        query = query.filter(RestaurantStockTransfer.transfer_type == transfer_type.upper())

    transfers = query.order_by(RestaurantStockTransfer.created_at.desc()).offset(offset).limit(limit).all()
    return [map_transfer_to_response(t) for t in transfers]


@router.get("/next-number")
def get_next_transfer_number(
    outlet_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Returns the next sequential transfer number for the current month.
    """
    outlet = resolve_outlet(db, outlet_id)
    next_number = generate_transfer_number(db, outlet.tenant_id)
    return {"transfer_number": next_number}


@router.get("/{transfer_id}", response_model=StockTransferResponse)
def get_stock_transfer_detail(
    transfer_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Get full details of a specific stock transfer with line items.
    """
    transfer = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.to_outlet),
            joinedload(RestaurantStockTransfer.initiated_by),
            joinedload(RestaurantStockTransfer.dispatched_by),
            joinedload(RestaurantStockTransfer.received_by),
            joinedload(RestaurantStockTransfer.items)
        )
        .filter(RestaurantStockTransfer.id == transfer_id)
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Stock transfer not found")

    return map_transfer_to_response(transfer)


@router.post("", response_model=StockTransferResponse, status_code=status.HTTP_201_CREATED)
def create_stock_transfer(
    payload: StockTransferCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Create a new Stock Transfer in DRAFT status.
    Handles:
    - Multi-branch (INTER_BRANCH) & Station-to-Station (INTER_STATION)
    - Automatic destination ingredient resolution and auto-cloning across branches
    - Dual-UOM input (PURCHASE or RECIPE)
    - Sequential tenant-isolated transfer number
    """
    if not payload.items:
        raise HTTPException(status_code=400, detail="Transfer must contain at least one item")

    from_outlet = resolve_outlet(db, payload.from_outlet_id)
    to_outlet = resolve_outlet(db, payload.to_outlet_id) if payload.to_outlet_id else from_outlet

    transfer_type = (payload.transfer_type or "INTER_BRANCH").upper()
    if from_outlet.id == to_outlet.id:
        transfer_type = "INTER_STATION"

    transfer_number = generate_transfer_number(db, from_outlet.tenant_id)

    transfer = RestaurantStockTransfer(
        tenant_id=from_outlet.tenant_id,
        transfer_number=transfer_number,
        transfer_type=transfer_type,
        from_outlet_id=from_outlet.id,
        to_outlet_id=to_outlet.id,
        from_station=payload.from_station or "Central Store",
        to_station=payload.to_station or "Kitchen Main",
        status="DRAFT",
        initiated_by_id=current_user.id if current_user else None,
        vehicle_number=payload.vehicle_number,
        driver_name=payload.driver_name,
        driver_phone=payload.driver_phone,
        notes=payload.notes,
        total_items=0,
        total_valuation=Decimal("0.00")
    )
    db.add(transfer)
    db.flush()

    total_val = Decimal("0.00")
    items_count = 0

    for item_input in payload.items:
        # 1. Fetch source ingredient
        src_ing = db.query(RestaurantIngredient).filter(
            RestaurantIngredient.id == item_input.ingredient_id,
            RestaurantIngredient.outlet_id == from_outlet.id
        ).first()

        if not src_ing:
            raise HTTPException(
                status_code=404,
                detail=f"Source ingredient ID {item_input.ingredient_id} not found in outlet {from_outlet.name}"
            )

        # 2. Convert quantity to recipe UOM
        qty_in_recipe_uom = item_input.quantity
        if (item_input.input_uom or "RECIPE").upper() == "PURCHASE":
            conv_factor = src_ing.uom_conversion_factor or Decimal("1.0000")
            qty_in_recipe_uom = item_input.quantity * conv_factor

        unit_cost = src_ing.cost_per_unit or Decimal("0.0000")
        line_total_cost = (qty_in_recipe_uom * unit_cost).quantize(Decimal("0.01"))
        total_val += line_total_cost
        items_count += 1

        # 3. Resolve destination ingredient
        dest_ing_id = None
        if transfer_type == "INTER_STATION":
            # Same branch station movement
            dest_ing_id = src_ing.id
        else:
            # Multi-branch transfer
            if item_input.destination_ingredient_id:
                # Direct destination ID passed
                dest_match = db.query(RestaurantIngredient).filter(
                    RestaurantIngredient.id == item_input.destination_ingredient_id,
                    RestaurantIngredient.outlet_id == to_outlet.id
                ).first()
                if dest_match:
                    dest_ing_id = dest_match.id

            if not dest_ing_id:
                # Automatic resolution by SKU
                if src_ing.sku:
                    dest_by_sku = db.query(RestaurantIngredient).filter(
                        RestaurantIngredient.outlet_id == to_outlet.id,
                        RestaurantIngredient.sku == src_ing.sku,
                        RestaurantIngredient.is_active == True
                    ).first()
                    if dest_by_sku:
                        dest_ing_id = dest_by_sku.id

            if not dest_ing_id:
                # Automatic resolution by normalized name + recipe unit
                dest_by_name = db.query(RestaurantIngredient).filter(
                    RestaurantIngredient.outlet_id == to_outlet.id,
                    func.lower(func.trim(RestaurantIngredient.name)) == src_ing.name.strip().lower(),
                    RestaurantIngredient.recipe_uom == src_ing.recipe_uom,
                    RestaurantIngredient.is_active == True
                ).first()
                if dest_by_name:
                    dest_ing_id = dest_by_name.id

            if not dest_ing_id:
                # Auto-seed / Auto-clone ingredient into target branch
                # Matches category if present in target branch
                target_cat_id = None
                if src_ing.category_id:
                    src_cat = db.query(RestaurantIngredientCategory).filter(
                        RestaurantIngredientCategory.id == src_ing.category_id
                    ).first()
                    if src_cat:
                        dest_cat = db.query(RestaurantIngredientCategory).filter(
                            RestaurantIngredientCategory.outlet_id == to_outlet.id,
                            RestaurantIngredientCategory.name == src_cat.name
                        ).first()
                        if dest_cat:
                            target_cat_id = dest_cat.id

                cloned_ing = RestaurantIngredient(
                    outlet_id=to_outlet.id,
                    tenant_id=to_outlet.tenant_id,
                    category_id=target_cat_id,
                    name=src_ing.name,
                    sku=src_ing.sku,
                    unit=src_ing.unit,
                    storage_zone=src_ing.storage_zone,
                    storage_location=src_ing.storage_location,
                    current_stock=Decimal("0.000"),
                    reorder_level=src_ing.reorder_level,
                    cost_per_unit=src_ing.cost_per_unit,
                    purchase_uom=src_ing.purchase_uom,
                    recipe_uom=src_ing.recipe_uom,
                    uom_conversion_factor=src_ing.uom_conversion_factor,
                    min_par_level=src_ing.min_par_level,
                    ideal_par_level=src_ing.ideal_par_level,
                    cost_per_purchase_unit=src_ing.cost_per_purchase_unit,
                    is_perishable=src_ing.is_perishable,
                    shelf_life_days=src_ing.shelf_life_days,
                    is_active=True
                )
                db.add(cloned_ing)
                db.flush()
                dest_ing_id = cloned_ing.id

        # 4. Create transfer item record
        t_item = RestaurantStockTransferItem(
            transfer_id=transfer.id,
            ingredient_id=src_ing.id,
            destination_ingredient_id=dest_ing_id,
            ingredient_name=src_ing.name,
            sku=src_ing.sku,
            unit=src_ing.recipe_uom or src_ing.unit or "G",
            quantity_requested=qty_in_recipe_uom,
            quantity_dispatched=Decimal("0.000"),
            quantity_received=Decimal("0.000"),
            quantity_variance=Decimal("0.000"),
            unit_cost=unit_cost,
            total_cost=line_total_cost,
            batch_number=item_input.batch_number,
            expiry_date=datetime.combine(item_input.expiry_date, datetime.min.time()) if item_input.expiry_date else None
        )
        db.add(t_item)

    transfer.total_items = items_count
    transfer.total_valuation = total_val

    db.commit()
    db.refresh(transfer)

    return map_transfer_to_response(transfer)


@router.post("/{transfer_id}/dispatch", response_model=StockTransferResponse)
def dispatch_stock_transfer(
    transfer_id: UUID,
    payload: Optional[StockTransferDispatchInput] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_restaurant_staff)
):
    """
    Dispatch stock transfer: transitions from DRAFT -> IN_TRANSIT.
    - Acquires row-level locks on source ingredients (with_for_update)
    - Validates sufficient stock if negative stock is disallowed
    - INTER_BRANCH: Deducts stock from source outlet and writes TRANSFER_OUT ledger entries
    - INTER_STATION: No change to overall current_stock; writes STATION_TRANSFER audit entry
    """
    transfer = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.to_outlet),
            joinedload(RestaurantStockTransfer.items)
        )
        .filter(RestaurantStockTransfer.id == transfer_id)
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Stock transfer not found")

    if transfer.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot dispatch transfer in status '{transfer.status}'. Only DRAFT transfers can be dispatched."
        )

    from_outlet = transfer.from_outlet
    to_outlet = transfer.to_outlet

    if payload:
        if payload.vehicle_number:
            transfer.vehicle_number = payload.vehicle_number
        if payload.driver_name:
            transfer.driver_name = payload.driver_name
        if payload.driver_phone:
            transfer.driver_phone = payload.driver_phone
        if payload.sender_signature:
            transfer.sender_signature = payload.sender_signature
        if payload.driver_signature:
            transfer.driver_signature = payload.driver_signature
        if payload.notes:
            transfer.notes = f"{transfer.notes or ''}\nDispatch note: {payload.notes}".strip()

    transfer.dispatched_at = get_current_time()
    transfer.dispatched_by_id = current_user.id if current_user else None

    # Process items
    for item in transfer.items:
        # Lock source ingredient
        src_ing = (
            db.query(RestaurantIngredient)
            .filter(RestaurantIngredient.id == item.ingredient_id)
            .with_for_update()
            .first()
        )
        if not src_ing:
            raise HTTPException(status_code=404, detail=f"Source ingredient {item.ingredient_name} not found")

        dispatch_qty = item.quantity_requested
        item.quantity_dispatched = dispatch_qty
        item.unit_cost = src_ing.cost_per_unit or Decimal("0.0000")
        item.total_cost = (dispatch_qty * item.unit_cost).quantize(Decimal("0.01"))

        if transfer.transfer_type == "INTER_STATION":
            # Mode B: Internal station movement does NOT alter outlet total current_stock
            station_entry = RestaurantStockLedger(
                ingredient_id=src_ing.id,
                outlet_id=from_outlet.id,
                tenant_id=from_outlet.tenant_id,
                signed_quantity=Decimal("0.000"), # Zero net inventory change
                unit_cost_at_time=src_ing.cost_per_unit or Decimal("0.0000"),
                total_cost=Decimal("0.00"),
                reason="STATION_TRANSFER",
                source_type="stock_transfer",
                source_id=str(transfer.id),
                actor_id=current_user.id if current_user else None,
                notes=f"Station Transfer dispatched: {transfer.from_station} -> {transfer.to_station} ({dispatch_qty} {item.unit})"
            )
            db.add(station_entry)
        else:
            # Mode A: Multi-branch transfer
            allow_negative = getattr(from_outlet, "allow_negative_stock", True)
            if not allow_negative and (src_ing.current_stock < dispatch_qty):
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {src_ing.name}. Available: {src_ing.current_stock} {src_ing.recipe_uom}, requested: {dispatch_qty}"
                )

            # Deduct from source branch stock
            src_ing.current_stock -= dispatch_qty

            # Append-only Stock Ledger for source branch
            source_ledger = RestaurantStockLedger(
                ingredient_id=src_ing.id,
                outlet_id=from_outlet.id,
                tenant_id=from_outlet.tenant_id,
                signed_quantity=-dispatch_qty,
                unit_cost_at_time=src_ing.cost_per_unit or Decimal("0.0000"),
                total_cost=item.total_cost,
                reason="TRANSFER_OUT",
                source_type="stock_transfer",
                source_id=str(transfer.id),
                actor_id=current_user.id if current_user else None,
                notes=f"Dispatched via transfer {transfer.transfer_number} to {to_outlet.name} ({transfer.to_station or 'Store'})"
            )
            db.add(source_ledger)

    transfer.status = "IN_TRANSIT"
    db.commit()
    db.refresh(transfer)

    return map_transfer_to_response(transfer)


@router.post("/{transfer_id}/receive", response_model=StockTransferResponse)
def receive_stock_transfer(
    transfer_id: UUID,
    payload: StockTransferReceiveInput,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_restaurant_staff)
):
    """
    Receive stock transfer: transitions from IN_TRANSIT -> COMPLETED.
    - Reconciles received quantities against dispatched quantities
    - Transit Variance Handling: If quantity_received < quantity_dispatched, logs TRANSIT_LOSS in stock ledger
    - Re-blends Moving Average Cost (WAC) safely at destination outlet
    - Multi-tenant, row-locked execution
    """
    transfer = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.to_outlet),
            joinedload(RestaurantStockTransfer.items)
        )
        .filter(RestaurantStockTransfer.id == transfer_id)
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Stock transfer not found")

    if transfer.status != "IN_TRANSIT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive transfer in status '{transfer.status}'. Only IN_TRANSIT transfers can be received."
        )

    from_outlet = transfer.from_outlet
    to_outlet = transfer.to_outlet

    if payload.notes:
        transfer.notes = f"{transfer.notes or ''}\nReceive note: {payload.notes}".strip()
    if payload.receiver_signature:
        transfer.receiver_signature = payload.receiver_signature

    transfer.received_at = get_current_time()
    transfer.received_by_id = current_user.id if current_user else None

    # Map incoming received payload by item ID
    recv_map = {item_input.item_id: item_input for item_input in payload.items}

    for item in transfer.items:
        recv_data = recv_map.get(item.id)
        if not recv_data:
            raise HTTPException(
                status_code=400,
                detail=f"Missing receive data for item '{item.ingredient_name}' (ID: {item.id})"
            )

        # Dual-UOM handling for received qty
        received_qty = recv_data.quantity_received
        if (recv_data.input_uom or "RECIPE").upper() == "PURCHASE":
            dest_lookup = db.query(RestaurantIngredient).filter(
                RestaurantIngredient.id == item.destination_ingredient_id
            ).first()
            if dest_lookup and dest_lookup.uom_conversion_factor:
                received_qty = received_qty * dest_lookup.uom_conversion_factor

        variance = item.quantity_dispatched - received_qty # > 0 means loss/spillage
        item.quantity_received = received_qty
        item.quantity_variance = variance
        item.variance_reason = recv_data.variance_reason

        if variance > Decimal("0.000"):
            # Transit loss / spillage occurred in route!
            loss_cost = (variance * item.unit_cost).quantize(Decimal("0.01"))
            reason_str = recv_data.variance_reason or "Transit Spillage / Loss"

            # Log audit entry in source ledger for transit loss
            loss_entry = RestaurantStockLedger(
                ingredient_id=item.ingredient_id,
                outlet_id=from_outlet.id,
                tenant_id=from_outlet.tenant_id,
                signed_quantity=-variance,
                unit_cost_at_time=item.unit_cost,
                total_cost=loss_cost,
                reason="TRANSIT_LOSS",
                source_type="stock_transfer",
                source_id=str(transfer.id),
                actor_id=current_user.id if current_user else None,
                notes=f"Transit shrinkage on {transfer.transfer_number} (dispatched {item.quantity_dispatched}, received {received_qty}). Reason: {reason_str}"
            )
            db.add(loss_entry)

        if transfer.transfer_type == "INTER_STATION":
            # Mode B: Internal station receipt is informational
            station_entry = RestaurantStockLedger(
                ingredient_id=item.ingredient_id,
                outlet_id=to_outlet.id,
                tenant_id=to_outlet.tenant_id,
                signed_quantity=Decimal("0.000"),
                unit_cost_at_time=item.unit_cost,
                total_cost=Decimal("0.00"),
                reason="STATION_TRANSFER_RECEIVED",
                source_type="stock_transfer",
                source_id=str(transfer.id),
                actor_id=current_user.id if current_user else None,
                notes=f"Station Transfer received at {transfer.to_station} ({received_qty} {item.unit})"
            )
            db.add(station_entry)
        else:
            # Mode A: Destination branch stock intake
            dest_ing = (
                db.query(RestaurantIngredient)
                .filter(RestaurantIngredient.id == item.destination_ingredient_id)
                .with_for_update()
                .first()
            )
            if not dest_ing:
                raise HTTPException(
                    status_code=404,
                    detail=f"Destination ingredient for '{item.ingredient_name}' not found at {to_outlet.name}"
                )

            old_dest_stock = dest_ing.current_stock or Decimal("0.000")
            old_dest_cost = dest_ing.cost_per_unit or Decimal("0.0000")
            landed_cost = item.unit_cost or Decimal("0.0000")

            # Safe Moving Average Cost (WAC) Calculation:
            # If current stock is zero or negative (due to POS rush sales before transfer received),
            # reset WAC directly to landed unit cost to avoid negative denominator corruption.
            if old_dest_stock <= Decimal("0.000"):
                new_wac = landed_cost
            else:
                total_received_val = received_qty * landed_cost
                total_existing_val = old_dest_stock * old_dest_cost
                new_wac = ((total_existing_val + total_received_val) / (old_dest_stock + received_qty)).quantize(Decimal("0.0001"))

            dest_ing.current_stock = old_dest_stock + received_qty
            dest_ing.cost_per_unit = new_wac
            dest_ing.last_restocked_at = get_current_time()

            # Append to destination branch stock ledger
            dest_ledger = RestaurantStockLedger(
                ingredient_id=dest_ing.id,
                outlet_id=to_outlet.id,
                tenant_id=to_outlet.tenant_id,
                signed_quantity=+received_qty,
                unit_cost_at_time=landed_cost,
                total_cost=(received_qty * landed_cost).quantize(Decimal("0.01")),
                reason="TRANSFER_IN",
                source_type="stock_transfer",
                source_id=str(transfer.id),
                actor_id=current_user.id if current_user else None,
                notes=f"Received via {transfer.transfer_number} from {from_outlet.name} ({transfer.from_station or 'Store'})"
            )
            db.add(dest_ledger)

    transfer.status = "COMPLETED"
    db.commit()
    db.refresh(transfer)

    return map_transfer_to_response(transfer)


@router.post("/{transfer_id}/cancel", response_model=StockTransferResponse)
def cancel_stock_transfer(
    transfer_id: UUID,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_restaurant_manager)
):
    """
    Cancel a stock transfer.
    - If DRAFT: immediately marks as CANCELLED.
    - If IN_TRANSIT (for INTER_BRANCH): safely reverts deducted stock on source ingredients and records REVERSAL ledger entries.
    - If COMPLETED: raises 400 error (cannot cancel completed transfer).
    """
    transfer = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.items)
        )
        .filter(RestaurantStockTransfer.id == transfer_id)
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Stock transfer not found")

    if transfer.status == "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a COMPLETED transfer. Please initiate a new return transfer."
        )

    if transfer.status == "CANCELLED":
        return map_transfer_to_response(transfer)

    from_outlet = transfer.from_outlet

    if transfer.status == "IN_TRANSIT" and transfer.transfer_type != "INTER_STATION":
        # Revert deducted stock back to source branch
        for item in transfer.items:
            src_ing = (
                db.query(RestaurantIngredient)
                .filter(RestaurantIngredient.id == item.ingredient_id)
                .with_for_update()
                .first()
            )
            if src_ing and item.quantity_dispatched > Decimal("0.000"):
                src_ing.current_stock += item.quantity_dispatched

                rev_entry = RestaurantStockLedger(
                    ingredient_id=src_ing.id,
                    outlet_id=from_outlet.id,
                    tenant_id=from_outlet.tenant_id,
                    signed_quantity=+item.quantity_dispatched,
                    unit_cost_at_time=item.unit_cost,
                    total_cost=item.total_cost,
                    reason="REVERSAL",
                    source_type="stock_transfer",
                    source_id=str(transfer.id),
                    actor_id=current_user.id if current_user else None,
                    notes=f"Reversal of cancelled transfer {transfer.transfer_number}. Reason: {reason or 'Cancelled by manager'}"
                )
                db.add(rev_entry)

    transfer.status = "CANCELLED"
    if reason:
        transfer.notes = f"{transfer.notes or ''}\nCancellation Reason: {reason}".strip()

    db.commit()
    db.refresh(transfer)

    return map_transfer_to_response(transfer)


# ----------------- DIGITAL CHALLAN / BILL RENDERING -----------------

transfer_template_env = Environment(loader=FileSystemLoader(searchpath="./templates"))

def render_transfer_challan_html(transfer: RestaurantStockTransfer, autoprint: bool = False) -> str:
    from_outlet = transfer.from_outlet
    to_outlet = transfer.to_outlet

    dispatched_by_name = (
        transfer.dispatched_by.name or transfer.dispatched_by.username
        if transfer.dispatched_by else (transfer.initiated_by.name if transfer.initiated_by else "Storekeeper")
    )
    received_by_name = (
        transfer.received_by.name or transfer.received_by.username
        if transfer.received_by else "Pending Verification"
    )

    items_data = []
    total_qty_dispatched = Decimal("0.00")
    total_qty_received = Decimal("0.00")
    total_variance_cost = Decimal("0.00")
    has_variance = False

    for it in (transfer.items or []):
        qty_req = it.quantity_requested or Decimal("0.00")
        qty_disp = it.quantity_dispatched or Decimal("0.00")
        qty_recv = it.quantity_received or Decimal("0.00")
        var = it.quantity_variance or Decimal("0.00")
        u_cost = it.unit_cost or Decimal("0.00")
        t_cost = it.total_cost or Decimal("0.00")

        total_qty_dispatched += qty_disp
        total_qty_received += qty_recv

        if var > Decimal("0.00"):
            has_variance = True
            total_variance_cost += (var * u_cost)

        items_data.append({
            "ingredient_name": it.ingredient_name,
            "sku": it.sku,
            "unit": it.unit,
            "quantity_requested": float(qty_req),
            "quantity_dispatched": float(qty_disp),
            "quantity_received": float(qty_recv),
            "quantity_variance": float(var),
            "is_loss": float(var) > 0.0001,
            "is_surplus": float(var) < -0.0001,
            "unit_cost": float(u_cost),
            "total_cost": float(t_cost),
            "variance_reason": it.variance_reason,
            "batch_number": it.batch_number
        })

    created_fmt = transfer.created_at.strftime("%d %b %Y, %I:%M %p") if transfer.created_at else "N/A"
    disp_fmt = transfer.dispatched_at.strftime("%d %b %Y, %I:%M %p") if transfer.dispatched_at else "N/A"
    recv_fmt = transfer.received_at.strftime("%d %b %Y, %I:%M %p") if transfer.received_at else "N/A"

    template = transfer_template_env.get_template("stock_transfer_bill_template.html")
    return template.render(
        transfer=transfer,
        from_outlet=from_outlet,
        to_outlet=to_outlet,
        brand_name=from_outlet.name if from_outlet else "SirfBill Restaurant",
        items=items_data,
        has_variance=has_variance,
        total_variance_cost=float(total_variance_cost),
        total_qty_dispatched=float(total_qty_dispatched),
        total_qty_received=float(total_qty_received),
        dispatched_by_name=dispatched_by_name,
        received_by_name=received_by_name,
        sender_signature=transfer.sender_signature,
        driver_signature=transfer.driver_signature,
        receiver_signature=transfer.receiver_signature,
        created_date_formatted=created_fmt,
        dispatched_at_formatted=disp_fmt,
        received_at_formatted=recv_fmt,
        autoprint=autoprint
    )


@router.get("/{transfer_id}/bill", response_class=HTMLResponse)
@router.get("/{transfer_id}/print", response_class=HTMLResponse)
def get_stock_transfer_digital_bill(
    transfer_id: UUID,
    autoprint: bool = Query(False, description="Set to true to immediately open system print dialog"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Renders the responsive Digital Bill / Stock Transfer Delivery Challan.
    Can be viewed on screen, embedded in Flutter WebView/Dialog, or printed as A4 / PDF.
    Pass ?autoprint=true to trigger the print dialog automatically.
    """
    transfer = (
        db.query(RestaurantStockTransfer)
        .options(
            joinedload(RestaurantStockTransfer.from_outlet),
            joinedload(RestaurantStockTransfer.to_outlet),
            joinedload(RestaurantStockTransfer.initiated_by),
            joinedload(RestaurantStockTransfer.dispatched_by),
            joinedload(RestaurantStockTransfer.received_by),
            joinedload(RestaurantStockTransfer.items)
        )
        .filter(RestaurantStockTransfer.id == transfer_id)
        .first()
    )
    if not transfer:
        raise HTTPException(status_code=404, detail="Stock transfer not found")

    html_content = render_transfer_challan_html(transfer, autoprint=autoprint)
    return HTMLResponse(content=html_content)

