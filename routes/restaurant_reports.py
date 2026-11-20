import uuid
from typing import List, Optional, Dict
from uuid import UUID
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from models.database import get_db
from models.user import User
from models.restaurant_order import RestaurantOrder
from models.restaurant_order_line import RestaurantOrderLine
from models.restaurant_tender import RestaurantTender
from models.restaurant_audit import RestaurantAuditEvent
from models.restaurant_ingredient import RestaurantIngredient, RestaurantIngredientCategory
from models.restaurant_stock_ledger import RestaurantStockLedger
from models.restaurant_recipe import RestaurantRecipe, RestaurantRecipeLine
from models.restaurant_stock_audit import RestaurantStockAudit, RestaurantStockAuditItem
from models.restaurant_procurement import RestaurantSupplier, RestaurantGRN, RestaurantGRNItem
from schemas.restaurant_reports import (
    SalesSummaryReport,
    TenderSummaryItem,
    DailySalesReportResponse,
    ItemSalesSummary,
    AuditSummaryItem,
    FoodCostVarianceItem,
    FoodCostVarianceReportResponse,
    StockMovementItem,
    StockMovementReportResponse,
    MenuEngineeringItem,
    MenuEngineeringReportResponse,
    ProcurementSupplierSummary,
    ProcurementAgingBucket,
    ProcurementReportResponse,
    ShrinkageIngredientItem,
    ShrinkageReportResponse,
)
from dependencies import get_restaurant_manager

router = APIRouter(
    prefix="/api/restaurant/reports",
    tags=["Restaurant - Reports & Costing Engine"]
)


# ============================================================================
# Existing Basic POS Reports
# ============================================================================
@router.get("/sales", response_model=DailySalesReportResponse)
def get_daily_sales_report(
    outlet_id: UUID,
    report_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Generate sales report by order type, taxes, discounts, and tender breakdown.
    """
    target_date = report_date or date.today()
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())

    orders_query = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.created_at >= start_dt)
        .filter(RestaurantOrder.created_at <= end_dt)
        .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "COMPLETED"]))
    )

    orders = orders_query.all()

    total_sales = Decimal("0.00")
    dine_in_sales = Decimal("0.00")
    takeaway_sales = Decimal("0.00")
    delivery_sales = Decimal("0.00")
    total_tax = Decimal("0.00")
    total_discount = Decimal("0.00")

    for o in orders:
        total_sales += (o.grand_total or Decimal("0.00"))
        total_tax += (o.tax_amount or Decimal("0.00"))
        total_discount += (o.discount_amount or Decimal("0.00"))
        if o.order_type == "DINE_IN":
            dine_in_sales += (o.grand_total or Decimal("0.00"))
        elif o.order_type == "TAKEAWAY":
            takeaway_sales += (o.grand_total or Decimal("0.00"))
        elif o.order_type == "DELIVERY":
            delivery_sales += (o.grand_total or Decimal("0.00"))

    summary = SalesSummaryReport(
        total_sales=total_sales,
        total_orders=len(orders),
        dine_in_sales=dine_in_sales,
        takeaway_sales=takeaway_sales,
        delivery_sales=delivery_sales,
        total_tax_collected=total_tax,
        total_discount_given=total_discount
    )

    # Tender Breakdown
    tender_rows = (
        db.query(
            RestaurantTender.method,
            func.coalesce(func.sum(RestaurantTender.amount), 0).label("amount"),
            func.count(RestaurantTender.id).label("count")
        )
        .join(RestaurantOrder, RestaurantTender.order_id == RestaurantOrder.id)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantTender.created_at >= start_dt)
        .filter(RestaurantTender.created_at <= end_dt)
        .filter(RestaurantTender.status == "COMPLETED")
        .group_by(RestaurantTender.method)
        .all()
    )

    tenders = [
        TenderSummaryItem(
            method=row.method,
            amount=Decimal(str(row.amount)),
            count=row.count
        )
        for row in tender_rows
    ]

    return DailySalesReportResponse(
        report_date=target_date,
        outlet_id=outlet_id,
        summary=summary,
        tenders=tenders
    )


@router.get("/items", response_model=List[ItemSalesSummary])
def get_item_sales_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Top selling menu items and variants with quantities and revenue generated.
    """
    s_date = start_date or date.today()
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    item_rows = (
        db.query(
            RestaurantOrderLine.item_name,
            RestaurantOrderLine.variant_name,
            func.sum(RestaurantOrderLine.quantity).label("quantity_sold"),
            func.sum(RestaurantOrderLine.line_total).label("total_revenue")
        )
        .join(RestaurantOrder, RestaurantOrderLine.order_id == RestaurantOrder.id)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.created_at >= start_dt)
        .filter(RestaurantOrder.created_at <= end_dt)
        .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "COMPLETED"]))
        .group_by(RestaurantOrderLine.item_name, RestaurantOrderLine.variant_name)
        .order_by(func.sum(RestaurantOrderLine.quantity).desc())
        .limit(limit)
        .all()
    )

    return [
        ItemSalesSummary(
            item_name=r.item_name,
            variant_name=r.variant_name or "Standard",
            quantity_sold=int(r.quantity_sold or 0),
            total_revenue=Decimal(str(r.total_revenue or 0.00))
        )
        for r in item_rows
    ]


@router.get("/audits", response_model=List[AuditSummaryItem])
def get_audit_event_summary(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Summary of voids, discount overrides, KOT reprints, and refunds.
    """
    s_date = start_date or date.today()
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    audit_rows = (
        db.query(
            RestaurantAuditEvent.action,
            func.count(RestaurantAuditEvent.id).label("count")
        )
        .filter(RestaurantAuditEvent.outlet_id == outlet_id)
        .filter(RestaurantAuditEvent.created_at >= start_dt)
        .filter(RestaurantAuditEvent.created_at <= end_dt)
        .group_by(RestaurantAuditEvent.action)
        .all()
    )

    return [
        AuditSummaryItem(
            action=r.action,
            count=r.count
        )
        for r in audit_rows
    ]


# ============================================================================
# 1. Food Cost Variance Report (Theoretical vs. Actual COGS)
# ============================================================================
@router.get("/food-cost-variance", response_model=FoodCostVarianceReportResponse)
def get_food_cost_variance_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Executive Report 1:
    Compares Theoretical COGS (BOM consumption via KOTs) against Actual COGS.
    Isolates Kitchen Wastage loss and Physical Audit Deficit Shrinkage.
    """
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    # Total Food Sales in period
    food_sales_res = (
        db.query(func.coalesce(func.sum(RestaurantOrder.grand_total), 0))
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.created_at >= start_dt)
        .filter(RestaurantOrder.created_at <= end_dt)
        .filter(RestaurantOrder.status == "COMPLETED")
        .scalar()
    )
    total_food_sales = Decimal(str(food_sales_res or 0.00))

    # All active ingredients for outlet
    ingredients = (
        db.query(RestaurantIngredient)
        .filter(RestaurantIngredient.outlet_id == outlet_id)
        .filter(RestaurantIngredient.is_active == True)
        .all()
    )

    # Fetch stock ledger entries for the period
    ledger_entries = (
        db.query(
            RestaurantStockLedger.ingredient_id,
            RestaurantStockLedger.reason,
            func.sum(RestaurantStockLedger.signed_quantity).label("sum_qty"),
            func.sum(RestaurantStockLedger.total_cost).label("sum_cost")
        )
        .filter(RestaurantStockLedger.outlet_id == outlet_id)
        .filter(RestaurantStockLedger.created_at >= start_dt)
        .filter(RestaurantStockLedger.created_at <= end_dt)
        .group_by(RestaurantStockLedger.ingredient_id, RestaurantStockLedger.reason)
        .all()
    )

    # Map by (ingredient_id, reason)
    ledger_map: Dict[UUID, Dict[str, Dict[str, Decimal]]] = {}
    for row in ledger_entries:
        ing_id = row.ingredient_id
        if ing_id not in ledger_map:
            ledger_map[ing_id] = {}
        ledger_map[ing_id][row.reason] = {
            "qty": abs(Decimal(str(row.sum_qty or 0.00))),
            "cost": Decimal(str(row.sum_cost or 0.00))
        }

    # Fetch Physical Audit Deficits in period
    audit_deficits = (
        db.query(
            RestaurantStockAuditItem.ingredient_id,
            func.sum(func.abs(RestaurantStockAuditItem.variance)).label("deficit_qty"),
            func.sum(RestaurantStockAuditItem.variance_rupees).label("deficit_cost")
        )
        .join(RestaurantStockAudit, RestaurantStockAuditItem.audit_id == RestaurantStockAudit.id)
        .filter(RestaurantStockAudit.outlet_id == outlet_id)
        .filter(RestaurantStockAudit.audit_date >= s_date)
        .filter(RestaurantStockAudit.audit_date <= e_date)
        .filter(RestaurantStockAuditItem.status == "DEFICIT")
        .group_by(RestaurantStockAuditItem.ingredient_id)
        .all()
    )
    audit_map = {
        row.ingredient_id: {
            "qty": Decimal(str(row.deficit_qty or 0.00)),
            "cost": Decimal(str(row.deficit_cost or 0.00))
        }
        for row in audit_deficits
    }

    breakdown_list = []
    total_theoretical_cogs = Decimal("0.00")
    total_wastage_loss = Decimal("0.00")
    total_audit_shrinkage = Decimal("0.00")

    for ing in ingredients:
        ing_ledger = ledger_map.get(ing.id, {})
        consumption_data = ing_ledger.get("ORDER_CONSUMPTION", {"qty": Decimal("0.00"), "cost": Decimal("0.00")})
        wastage_data = ing_ledger.get("WASTAGE", {"qty": Decimal("0.00"), "cost": Decimal("0.00")})
        audit_data = audit_map.get(ing.id, {"qty": Decimal("0.00"), "cost": Decimal("0.00")})

        theo_qty = consumption_data["qty"]
        theo_cost = consumption_data["cost"]
        waste_qty = wastage_data["qty"]
        waste_cost = wastage_data["cost"]
        audit_qty = audit_data["qty"]
        audit_cost = audit_data["cost"]

        actual_qty = theo_qty + waste_qty + audit_qty
        actual_cost = theo_cost + waste_cost + audit_cost

        variance_cost = actual_cost - theo_cost
        variance_pct = ((variance_cost / theo_cost) * Decimal("100")).quantize(Decimal("0.1")) if theo_cost > 0 else Decimal("0.0")

        total_theoretical_cogs += theo_cost
        total_wastage_loss += waste_cost
        total_audit_shrinkage += audit_cost

        # Only list ingredients that have movement or consumption
        if actual_qty > 0 or theo_qty > 0 or waste_qty > 0 or audit_qty > 0:
            category_name = ing.category.name if ing.category else "Uncategorized"
            breakdown_list.append(
                FoodCostVarianceItem(
                    ingredient_id=ing.id,
                    ingredient_name=ing.name,
                    category_name=category_name,
                    unit=ing.recipe_uom or ing.unit or "G",
                    theoretical_consumed_qty=theo_qty,
                    theoretical_cost=theo_cost,
                    actual_consumed_qty=actual_qty,
                    actual_cost=actual_cost,
                    kitchen_wastage_qty=waste_qty,
                    kitchen_wastage_cost=waste_cost,
                    audit_shrinkage_qty=audit_qty,
                    audit_shrinkage_cost=audit_cost,
                    variance_cost=variance_cost,
                    variance_pct=variance_pct
                )
            )

    actual_cogs = total_theoretical_cogs + total_wastage_loss + total_audit_shrinkage
    unexplained_variance = actual_cogs - total_theoretical_cogs
    variance_pct_sales = ((unexplained_variance / total_food_sales) * Decimal("100")).quantize(Decimal("0.1")) if total_food_sales > 0 else Decimal("0.0")
    theo_cogs_pct = ((total_theoretical_cogs / total_food_sales) * Decimal("100")).quantize(Decimal("0.1")) if total_food_sales > 0 else Decimal("0.0")
    actual_cogs_pct = ((actual_cogs / total_food_sales) * Decimal("100")).quantize(Decimal("0.1")) if total_food_sales > 0 else Decimal("0.0")

    return FoodCostVarianceReportResponse(
        outlet_id=outlet_id,
        start_date=s_date,
        end_date=e_date,
        total_food_sales=total_food_sales,
        theoretical_cogs=total_theoretical_cogs,
        actual_cogs=actual_cogs,
        logged_wastage_loss=total_wastage_loss,
        physical_audit_shrinkage=total_audit_shrinkage,
        unexplained_variance=unexplained_variance,
        variance_pct_of_sales=variance_pct_sales,
        theoretical_cogs_pct=theo_cogs_pct,
        actual_cogs_pct=actual_cogs_pct,
        breakdown=breakdown_list
    )


# ============================================================================
# 2. Stock Movement & Inventory Valuation Report
# ============================================================================
@router.get("/stock-movement", response_model=StockMovementReportResponse)
def get_stock_movement_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Executive Report 2:
    Stock Movement & Valuation Report.
    Opening + GRN In +/- Transfers - KOT Sold - Wastage +/- Physical Audit = Closing Stock & Valuation.
    """
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    ingredients = (
        db.query(RestaurantIngredient)
        .filter(RestaurantIngredient.outlet_id == outlet_id)
        .filter(RestaurantIngredient.is_active == True)
        .all()
    )

    items_list = []
    total_closing_valuation = Decimal("0.00")

    for ing in ingredients:
        # Opening Qty = Sum of signed quantities before start_dt
        opening_res = (
            db.query(func.coalesce(func.sum(RestaurantStockLedger.signed_quantity), 0))
            .filter(RestaurantStockLedger.ingredient_id == ing.id)
            .filter(RestaurantStockLedger.created_at < start_dt)
            .scalar()
        )
        opening_qty = Decimal(str(opening_res or 0.00))

        # Movement in range grouped by reason
        movement_rows = (
            db.query(
                RestaurantStockLedger.reason,
                func.sum(RestaurantStockLedger.signed_quantity).label("sum_signed_qty")
            )
            .filter(RestaurantStockLedger.ingredient_id == ing.id)
            .filter(RestaurantStockLedger.created_at >= start_dt)
            .filter(RestaurantStockLedger.created_at <= end_dt)
            .group_by(RestaurantStockLedger.reason)
            .all()
        )
        m_dict = {row.reason: Decimal(str(row.sum_signed_qty or 0.00)) for row in movement_rows}

        received_grn_qty = max(Decimal("0.00"), m_dict.get("PURCHASE_RECEIVED", Decimal("0.00")))
        transfers_net_qty = m_dict.get("TRANSFER_IN", Decimal("0.00")) + m_dict.get("TRANSFER_OUT", Decimal("0.00"))
        kot_sold_qty = abs(m_dict.get("ORDER_CONSUMPTION", Decimal("0.00")))
        wastage_qty = abs(m_dict.get("WASTAGE", Decimal("0.00")))
        audit_adjust_qty = m_dict.get("PHYSICAL_COUNT_ADJUSTMENT", Decimal("0.00"))

        closing_qty = opening_qty + received_grn_qty + transfers_net_qty - kot_sold_qty - wastage_qty + audit_adjust_qty
        if closing_qty < Decimal("0.00"):
            closing_qty = Decimal("0.00")

        cost_unit = ing.cost_per_unit or Decimal("0.00")
        closing_valuation = (closing_qty * cost_unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_closing_valuation += closing_valuation

        items_list.append(
            StockMovementItem(
                ingredient_id=ing.id,
                ingredient_name=ing.name,
                category_name=ing.category.name if ing.category else "General",
                unit=ing.recipe_uom or ing.unit or "G",
                cost_per_unit=cost_unit,
                opening_qty=opening_qty,
                received_grn_qty=received_grn_qty,
                transfers_net_qty=transfers_net_qty,
                kot_sold_qty=kot_sold_qty,
                wastage_qty=wastage_qty,
                audit_adjust_qty=audit_adjust_qty,
                closing_qty=closing_qty,
                closing_valuation=closing_valuation
            )
        )

    return StockMovementReportResponse(
        outlet_id=outlet_id,
        start_date=s_date,
        end_date=e_date,
        total_closing_valuation=total_closing_valuation,
        items=items_list
    )


# ============================================================================
# 3. Menu Engineering & Plate Cost Report (BCG Matrix)
# ============================================================================
@router.get("/menu-engineering", response_model=MenuEngineeringReportResponse)
def get_menu_engineering_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Executive Report 3:
    Menu Engineering & Dish Profitability Matrix.
    Computes Plate Cost, Gross Margin, Food Cost %, and BCG Quadrant (STAR, PLOWHORSE, PUZZLE, DOG).
    """
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    # Aggregate sales by menu item from order lines
    order_items = (
        db.query(
            RestaurantOrderLine.item_id,
            RestaurantOrderLine.item_name,
            RestaurantOrderLine.variant_name,
            func.avg(RestaurantOrderLine.unit_price).label("avg_price"),
            func.sum(RestaurantOrderLine.quantity).label("total_qty"),
            func.sum(RestaurantOrderLine.line_total).label("total_revenue")
        )
        .join(RestaurantOrder, RestaurantOrderLine.order_id == RestaurantOrder.id)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.created_at >= start_dt)
        .filter(RestaurantOrder.created_at <= end_dt)
        .filter(RestaurantOrder.status == "COMPLETED")
        .group_by(
            RestaurantOrderLine.item_id,
            RestaurantOrderLine.item_name,
            RestaurantOrderLine.variant_name
        )
        .all()
    )

    # Pre-calculate plate costs for recipes
    recipes = db.query(RestaurantRecipe).filter(RestaurantRecipe.outlet_id == outlet_id).all()
    recipe_cost_map: Dict[str, Decimal] = {}
    for r in recipes:
        plate_cost = Decimal("0.00")
        for line in (r.lines or []):
            ing_cost = line.ingredient.cost_per_unit if line.ingredient else Decimal("0.00")
            yield_val = r.yield_servings if r.yield_servings and r.yield_servings > 0 else Decimal("1.00")
            plate_cost += (line.quantity_required / yield_val) * ing_cost
        key = f"{r.item_id}_{r.variant_name}"
        recipe_cost_map[key] = plate_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    raw_items = []
    total_food_cost_sum = Decimal("0.00")
    total_qty_sold_all = 0
    total_margin_all = Decimal("0.00")

    for row in order_items:
        selling_price = Decimal(str(row.avg_price or 0.00))
        variant = row.variant_name or "Standard"
        recipe_key = f"{row.item_id}_{variant}"
        fallback_key = f"{row.item_id}_Standard"

        # Theoretical plate cost from recipe or fallback to 30% baseline
        plate_cost = recipe_cost_map.get(recipe_key) or recipe_cost_map.get(fallback_key)
        if not plate_cost or plate_cost <= 0:
            plate_cost = (selling_price * Decimal("0.30")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        margin_rupees = selling_price - plate_cost
        food_cost_pct = ((plate_cost / selling_price) * Decimal("100")).quantize(Decimal("0.1")) if selling_price > 0 else Decimal("0.0")
        qty_sold = int(row.total_qty or 0)
        revenue = Decimal(str(row.total_revenue or 0.00))
        margin_total = margin_rupees * qty_sold

        total_food_cost_sum += food_cost_pct
        total_qty_sold_all += qty_sold
        total_margin_all += margin_total

        raw_items.append({
            "item_id": row.item_id or uuid.uuid4(),
            "item_name": row.item_name,
            "category_name": "Food & Beverage",
            "variant_name": variant,
            "selling_price": selling_price,
            "plate_cost": plate_cost,
            "gross_margin_rupees": margin_rupees,
            "food_cost_pct": food_cost_pct,
            "quantity_sold": qty_sold,
            "total_revenue": revenue,
            "total_margin": margin_total,
            "is_cost_alert": food_cost_pct > Decimal("35.0")
        })

    total_count = len(raw_items)
    avg_food_cost_pct = (total_food_cost_sum / total_count).quantize(Decimal("0.1")) if total_count > 0 else Decimal("0.0")
    avg_margin_threshold = (total_margin_all / total_qty_sold_all).quantize(Decimal("0.01")) if total_qty_sold_all > 0 else Decimal("0.00")
    avg_qty_threshold = total_qty_sold_all / total_count if total_count > 0 else 0

    stars_count = 0
    plowhorses_count = 0
    puzzles_count = 0
    dogs_count = 0

    menu_engineering_items = []
    for item in raw_items:
        # BCG Quadrant Classification
        high_pop = item["quantity_sold"] >= avg_qty_threshold
        high_margin = item["gross_margin_rupees"] >= avg_margin_threshold

        if high_pop and high_margin:
            quadrant = "STAR"
            stars_count += 1
        elif high_pop and not high_margin:
            quadrant = "PLOWHORSE"
            plowhorses_count += 1
        elif not high_pop and high_margin:
            quadrant = "PUZZLE"
            puzzles_count += 1
        else:
            quadrant = "DOG"
            dogs_count += 1

        menu_engineering_items.append(
            MenuEngineeringItem(
                item_id=item["item_id"],
                item_name=item["item_name"],
                category_name=item["category_name"],
                variant_name=item["variant_name"],
                selling_price=item["selling_price"],
                plate_cost=item["plate_cost"],
                gross_margin_rupees=item["gross_margin_rupees"],
                food_cost_pct=item["food_cost_pct"],
                quantity_sold=item["quantity_sold"],
                total_revenue=item["total_revenue"],
                total_margin=item["total_margin"],
                quadrant=quadrant,
                is_cost_alert=item["is_cost_alert"]
            )
        )

    return MenuEngineeringReportResponse(
        outlet_id=outlet_id,
        start_date=s_date,
        end_date=e_date,
        total_menu_items_analyzed=total_count,
        avg_food_cost_pct=avg_food_cost_pct,
        stars_count=stars_count,
        plowhorses_count=plowhorses_count,
        puzzles_count=puzzles_count,
        dogs_count=dogs_count,
        items=menu_engineering_items
    )


# ============================================================================
# 4. Procurement & GST Register Report (Vendor Spend & Input Tax)
# ============================================================================
@router.get("/procurement", response_model=ProcurementReportResponse)
def get_procurement_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Executive Report 4:
    Procurement & GST Input Tax Register.
    Vendor spend breakdown, GST input paid by tax slab (5%, 12%, 18%), and Unpaid GRN Aging.
    """
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    # Query all GRNs in date range
    grns = (
        db.query(RestaurantGRN)
        .filter(RestaurantGRN.outlet_id == outlet_id)
        .filter(RestaurantGRN.received_date >= start_dt)
        .filter(RestaurantGRN.received_date <= end_dt)
        .all()
    )

    # Group by supplier
    suppliers_data: Dict[UUID, Dict] = {}
    total_purchase_spend = Decimal("0.00")
    total_input_gst = Decimal("0.00")
    total_unpaid = Decimal("0.00")
    gst_5_total = Decimal("0.00")
    gst_12_total = Decimal("0.00")
    gst_18_total = Decimal("0.00")

    # Aging brackets
    aging_map = {
        "0-7 days": {"amount": Decimal("0.00"), "count": 0},
        "8-15 days": {"amount": Decimal("0.00"), "count": 0},
        "16-30 days": {"amount": Decimal("0.00"), "count": 0},
        "30+ days": {"amount": Decimal("0.00"), "count": 0},
    }

    today = date.today()

    for grn in grns:
        sup = grn.supplier
        sup_id = grn.supplier_id
        if sup_id not in suppliers_data:
            suppliers_data[sup_id] = {
                "supplier_id": sup_id,
                "supplier_name": sup.name if sup else "Unknown Supplier",
                "gstin": sup.gstin if sup else None,
                "grn_count": 0,
                "net_purchase_amount": Decimal("0.00"),
                "gst_5_amount": Decimal("0.00"),
                "gst_12_amount": Decimal("0.00"),
                "gst_18_amount": Decimal("0.00"),
                "total_tax_paid": Decimal("0.00"),
                "total_amount": Decimal("0.00"),
                "paid_amount": Decimal("0.00"),
                "unpaid_balance": Decimal("0.00"),
            }

        s_entry = suppliers_data[sup_id]
        s_entry["grn_count"] += 1
        s_entry["total_amount"] += grn.total_amount
        total_purchase_spend += grn.total_amount

        # Check payment status
        if grn.payment_status == "PAID":
            s_entry["paid_amount"] += grn.total_amount
        elif grn.payment_status == "PARTIAL":
            half_amt = (grn.total_amount / Decimal("2")).quantize(Decimal("0.01"))
            s_entry["paid_amount"] += half_amt
            s_entry["unpaid_balance"] += half_amt
            total_unpaid += half_amt
        else:
            s_entry["unpaid_balance"] += grn.total_amount
            total_unpaid += grn.total_amount

            # Aging computation
            grn_date = grn.invoice_date or grn.received_date.date()
            age_days = (today - grn_date).days
            if age_days <= 7:
                aging_map["0-7 days"]["amount"] += grn.total_amount
                aging_map["0-7 days"]["count"] += 1
            elif age_days <= 15:
                aging_map["8-15 days"]["amount"] += grn.total_amount
                aging_map["8-15 days"]["count"] += 1
            elif age_days <= 30:
                aging_map["16-30 days"]["amount"] += grn.total_amount
                aging_map["16-30 days"]["count"] += 1
            else:
                aging_map["30+ days"]["amount"] += grn.total_amount
                aging_map["30+ days"]["count"] += 1

        # Calculate line item taxes
        for item in (grn.items or []):
            rate = Decimal(str(item.tax_rate or 0))
            tax_amt = Decimal(str(item.tax_amount or 0.00))
            s_entry["total_tax_paid"] += tax_amt
            total_input_gst += tax_amt

            if rate == Decimal("5.00") or rate == Decimal("5"):
                s_entry["gst_5_amount"] += tax_amt
                gst_5_total += tax_amt
            elif rate == Decimal("12.00") or rate == Decimal("12"):
                s_entry["gst_12_amount"] += tax_amt
                gst_12_total += tax_amt
            elif rate == Decimal("18.00") or rate == Decimal("18"):
                s_entry["gst_18_amount"] += tax_amt
                gst_18_total += tax_amt

        s_entry["net_purchase_amount"] = s_entry["total_amount"] - s_entry["total_tax_paid"]

    supplier_summaries = [
        ProcurementSupplierSummary(
            supplier_id=v["supplier_id"],
            supplier_name=v["supplier_name"],
            gstin=v["gstin"],
            grn_count=v["grn_count"],
            net_purchase_amount=v["net_purchase_amount"],
            gst_5_amount=v["gst_5_amount"],
            gst_12_amount=v["gst_12_amount"],
            gst_18_amount=v["gst_18_amount"],
            total_tax_paid=v["total_tax_paid"],
            total_amount=v["total_amount"],
            paid_amount=v["paid_amount"],
            unpaid_balance=v["unpaid_balance"]
        )
        for v in suppliers_data.values()
    ]

    aging_buckets = [
        ProcurementAgingBucket(
            aging_bracket=bracket,
            unpaid_amount=data["amount"],
            invoice_count=data["count"]
        )
        for bracket, data in aging_map.items()
    ]

    return ProcurementReportResponse(
        outlet_id=outlet_id,
        start_date=s_date,
        end_date=e_date,
        total_purchase_spend=total_purchase_spend,
        total_input_gst_paid=total_input_gst,
        total_unpaid_payables=total_unpaid,
        gst_5_total=gst_5_total,
        gst_12_total=gst_12_total,
        gst_18_total=gst_18_total,
        suppliers=supplier_summaries,
        aging_buckets=aging_buckets
    )


# ============================================================================
# 5. Shrinkage & Wastage Breakdown Report
# ============================================================================
@router.get("/shrinkage", response_model=ShrinkageReportResponse)
def get_shrinkage_report(
    outlet_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    manager_user: User = Depends(get_restaurant_manager)
):
    """
    Executive Report 5:
    Shrinkage & Wastage Breakdown.
    Ranks top 20 cost-leaking ingredients across Spoilage, Burnt/Ruined, Customer Return, and Physical Audit Deficit.
    """
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    start_dt = datetime.combine(s_date, datetime.min.time())
    end_dt = datetime.combine(e_date, datetime.max.time())

    # Wastage entries from stock ledger
    wastage_entries = (
        db.query(RestaurantStockLedger)
        .filter(RestaurantStockLedger.outlet_id == outlet_id)
        .filter(RestaurantStockLedger.reason == "WASTAGE")
        .filter(RestaurantStockLedger.created_at >= start_dt)
        .filter(RestaurantStockLedger.created_at <= end_dt)
        .all()
    )

    # Audit deficit entries
    audit_deficits = (
        db.query(RestaurantStockAuditItem)
        .join(RestaurantStockAudit, RestaurantStockAuditItem.audit_id == RestaurantStockAudit.id)
        .filter(RestaurantStockAudit.outlet_id == outlet_id)
        .filter(RestaurantStockAudit.audit_date >= s_date)
        .filter(RestaurantStockAudit.audit_date <= e_date)
        .filter(RestaurantStockAuditItem.status == "DEFICIT")
        .all()
    )

    spoilage_total = Decimal("0.00")
    burnt_ruined_total = Decimal("0.00")
    customer_return_total = Decimal("0.00")
    audit_deficit_total = Decimal("0.00")

    ingredient_loss_map: Dict[UUID, Dict] = {}

    for w in wastage_entries:
        ing = w.ingredient
        ing_id = w.ingredient_id
        if ing_id not in ingredient_loss_map:
            ingredient_loss_map[ing_id] = {
                "ingredient_id": ing_id,
                "ingredient_name": ing.name if ing else "Unknown",
                "category_name": ing.category.name if ing and ing.category else "Uncategorized",
                "unit": ing.recipe_uom or (ing.unit if ing else "G"),
                "cost_per_unit": ing.cost_per_unit if ing else Decimal("0.00"),
                "total_lost_qty": Decimal("0.00"),
                "total_loss_rupees": Decimal("0.00"),
                "loss_breakdown": {
                    "SPOILAGE": 0.0,
                    "BURNT_RUINED": 0.0,
                    "CUSTOMER_RETURN": 0.0,
                    "AUDIT_DEFICIT": 0.0
                }
            }

        loss_amt = Decimal(str(w.total_cost or 0.00))
        qty_lost = abs(Decimal(str(w.signed_quantity or 0.00)))
        notes = (w.notes or "").upper()

        target_cat = "SPOILAGE"
        if "BURNT" in notes or "RUINED" in notes:
            target_cat = "BURNT_RUINED"
            burnt_ruined_total += loss_amt
        elif "RETURN" in notes:
            target_cat = "CUSTOMER_RETURN"
            customer_return_total += loss_amt
        else:
            spoilage_total += loss_amt

        item_entry = ingredient_loss_map[ing_id]
        item_entry["total_lost_qty"] += qty_lost
        item_entry["total_loss_rupees"] += loss_amt
        item_entry["loss_breakdown"][target_cat] += float(loss_amt)

    for a in audit_deficits:
        ing = a.ingredient
        ing_id = a.ingredient_id
        if ing_id not in ingredient_loss_map:
            ingredient_loss_map[ing_id] = {
                "ingredient_id": ing_id,
                "ingredient_name": a.ingredient_name or (ing.name if ing else "Unknown"),
                "category_name": ing.category.name if ing and ing.category else "Uncategorized",
                "unit": a.recipe_uom or (ing.recipe_uom if ing else "G"),
                "cost_per_unit": a.unit_cost_at_time or (ing.cost_per_unit if ing else Decimal("0.00")),
                "total_lost_qty": Decimal("0.00"),
                "total_loss_rupees": Decimal("0.00"),
                "loss_breakdown": {
                    "SPOILAGE": 0.0,
                    "BURNT_RUINED": 0.0,
                    "CUSTOMER_RETURN": 0.0,
                    "AUDIT_DEFICIT": 0.0
                }
            }

        loss_amt = Decimal(str(a.variance_rupees or 0.00))
        qty_lost = abs(Decimal(str(a.variance or 0.00)))
        audit_deficit_total += loss_amt

        item_entry = ingredient_loss_map[ing_id]
        item_entry["total_lost_qty"] += qty_lost
        item_entry["total_loss_rupees"] += loss_amt
        item_entry["loss_breakdown"]["AUDIT_DEFICIT"] += float(loss_amt)

    total_shrinkage = spoilage_total + burnt_ruined_total + customer_return_total + audit_deficit_total

    # Rank top 20 by loss rupees
    sorted_ingredients = sorted(
        ingredient_loss_map.values(),
        key=lambda x: x["total_loss_rupees"],
        reverse=True
    )[:20]

    top_leaking_items = [
        ShrinkageIngredientItem(
            ingredient_id=row["ingredient_id"],
            ingredient_name=row["ingredient_name"],
            category_name=row["category_name"],
            unit=row["unit"],
            cost_per_unit=row["cost_per_unit"],
            total_lost_qty=row["total_lost_qty"],
            total_loss_rupees=row["total_loss_rupees"],
            loss_breakdown=row["loss_breakdown"]
        )
        for row in sorted_ingredients
    ]

    return ShrinkageReportResponse(
        outlet_id=outlet_id,
        start_date=s_date,
        end_date=e_date,
        total_shrinkage_rupees=total_shrinkage,
        spoilage_total=spoilage_total,
        burnt_ruined_total=burnt_ruined_total,
        customer_return_total=customer_return_total,
        audit_deficit_total=audit_deficit_total,
        top_leaking_ingredients=top_leaking_items
    )
