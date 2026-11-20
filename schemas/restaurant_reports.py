from typing import List, Optional
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

# Existing Sales & Audit Reports
class SalesSummaryReport(BaseModel):
    total_sales: Decimal
    total_orders: int
    dine_in_sales: Decimal
    takeaway_sales: Decimal
    delivery_sales: Decimal
    total_tax_collected: Decimal
    total_discount_given: Decimal

class TenderSummaryItem(BaseModel):
    method: str
    amount: Decimal
    count: int

class DailySalesReportResponse(BaseModel):
    report_date: date
    outlet_id: UUID
    summary: SalesSummaryReport
    tenders: List[TenderSummaryItem]

class ItemSalesSummary(BaseModel):
    item_name: str
    variant_name: str
    quantity_sold: int
    total_revenue: Decimal

class AuditSummaryItem(BaseModel):
    action: str
    count: int


# ============================================================================
# The 5 Executive Reports & Food Costing Engine Schemas
# ============================================================================

# 1. Food Cost Variance Report
class FoodCostVarianceItem(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    category_name: Optional[str] = None
    unit: str
    theoretical_consumed_qty: Decimal
    theoretical_cost: Decimal
    actual_consumed_qty: Decimal
    actual_cost: Decimal
    kitchen_wastage_qty: Decimal
    kitchen_wastage_cost: Decimal
    audit_shrinkage_qty: Decimal
    audit_shrinkage_cost: Decimal
    variance_cost: Decimal # Actual Cost - Theoretical Cost
    variance_pct: Decimal  # Variance % against theoretical

class FoodCostVarianceReportResponse(BaseModel):
    outlet_id: UUID
    start_date: date
    end_date: date
    total_food_sales: Decimal
    theoretical_cogs: Decimal
    actual_cogs: Decimal
    logged_wastage_loss: Decimal
    physical_audit_shrinkage: Decimal
    unexplained_variance: Decimal # Actual COGS - Theoretical COGS
    variance_pct_of_sales: Decimal
    theoretical_cogs_pct: Decimal
    actual_cogs_pct: Decimal
    breakdown: List[FoodCostVarianceItem]


# 2. Stock Movement & Valuation Report
class StockMovementItem(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    category_name: Optional[str] = None
    unit: str
    cost_per_unit: Decimal
    opening_qty: Decimal
    received_grn_qty: Decimal
    transfers_net_qty: Decimal
    kot_sold_qty: Decimal
    wastage_qty: Decimal
    audit_adjust_qty: Decimal
    closing_qty: Decimal
    closing_valuation: Decimal # closing_qty * cost_per_unit

class StockMovementReportResponse(BaseModel):
    outlet_id: UUID
    start_date: date
    end_date: date
    total_closing_valuation: Decimal
    items: List[StockMovementItem]


# 3. Menu Engineering & Plate Cost Report
class MenuEngineeringItem(BaseModel):
    item_id: UUID
    item_name: str
    category_name: Optional[str] = None
    variant_name: str
    selling_price: Decimal
    plate_cost: Decimal
    gross_margin_rupees: Decimal
    food_cost_pct: Decimal
    quantity_sold: int
    total_revenue: Decimal
    total_margin: Decimal
    quadrant: str # "STAR", "PLOWHORSE", "PUZZLE", "DOG"
    is_cost_alert: bool # Food cost > 35% threshold

class MenuEngineeringReportResponse(BaseModel):
    outlet_id: UUID
    start_date: date
    end_date: date
    total_menu_items_analyzed: int
    avg_food_cost_pct: Decimal
    stars_count: int
    plowhorses_count: int
    puzzles_count: int
    dogs_count: int
    items: List[MenuEngineeringItem]


# 4. Procurement & GST Register Report
class ProcurementSupplierSummary(BaseModel):
    supplier_id: UUID
    supplier_name: str
    gstin: Optional[str] = None
    grn_count: int
    net_purchase_amount: Decimal
    gst_5_amount: Decimal
    gst_12_amount: Decimal
    gst_18_amount: Decimal
    total_tax_paid: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    unpaid_balance: Decimal

class ProcurementAgingBucket(BaseModel):
    aging_bracket: str # "0-7 days", "8-15 days", "16-30 days", "30+ days"
    unpaid_amount: Decimal
    invoice_count: int

class ProcurementReportResponse(BaseModel):
    outlet_id: UUID
    start_date: date
    end_date: date
    total_purchase_spend: Decimal
    total_input_gst_paid: Decimal
    total_unpaid_payables: Decimal
    gst_5_total: Decimal
    gst_12_total: Decimal
    gst_18_total: Decimal
    suppliers: List[ProcurementSupplierSummary]
    aging_buckets: List[ProcurementAgingBucket]


# 5. Shrinkage & Wastage Breakdown Report
class ShrinkageIngredientItem(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    category_name: Optional[str] = None
    unit: str
    cost_per_unit: Decimal
    total_lost_qty: Decimal
    total_loss_rupees: Decimal
    loss_breakdown: dict # {"SPOILAGE": 120.0, "BURNT_RUINED": 45.0, "CUSTOMER_RETURN": 0.0, "AUDIT_DEFICIT": 200.0}

class ShrinkageReportResponse(BaseModel):
    outlet_id: UUID
    start_date: date
    end_date: date
    total_shrinkage_rupees: Decimal
    spoilage_total: Decimal
    burnt_ruined_total: Decimal
    customer_return_total: Decimal
    audit_deficit_total: Decimal
    top_leaking_ingredients: List[ShrinkageIngredientItem]
