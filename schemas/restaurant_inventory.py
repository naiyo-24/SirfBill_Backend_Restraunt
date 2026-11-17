from typing import Optional, List
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ----------------- INGREDIENT CATEGORIES -----------------
class RestaurantIngredientCategoryBase(BaseModel):
    name: str = Field(..., max_length=100, description="e.g. Dry & Grain Pantry, Dairy & Cheese")
    code: Optional[str] = Field(None, max_length=50, description="e.g. DRY, DAIRY, MEAT, PRODUCE, SPICE, BAR")
    storage_zone_temp: Optional[str] = Field(None, max_length=150, description="e.g. Ambient Store (Shelf A-C), Walk-in Chiller (2°C - 4°C)")
    color_code: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True

class RestaurantIngredientCategoryCreate(RestaurantIngredientCategoryBase):
    outlet_id: Optional[UUID] = None

class RestaurantIngredientCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    code: Optional[str] = Field(None, max_length=50)
    storage_zone_temp: Optional[str] = Field(None, max_length=150)
    color_code: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class RestaurantIngredientCategoryResponse(RestaurantIngredientCategoryBase):
    id: UUID
    outlet_id: UUID
    tenant_id: UUID
    items_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------- INGREDIENTS -----------------
class RestaurantIngredientBase(BaseModel):
    name: str = Field(..., max_length=150)
    sku: Optional[str] = None
    code: Optional[str] = None
    unit: str = "G" # Base recipe cooking unit: G, ML, PCS, etc.
    purchase_uom: Optional[str] = "KG"
    recipe_uom: Optional[str] = "G"
    uom_conversion_factor: Optional[Decimal] = Decimal("1.0000")
    category_id: Optional[UUID] = None
    storage_zone: Optional[str] = None
    storage_location: Optional[str] = None
    current_stock: Decimal = Decimal("0.000")
    reorder_level: Decimal = Decimal("5.000")
    min_par_level: Optional[Decimal] = Decimal("0.000")
    ideal_par_level: Optional[Decimal] = Decimal("0.000")
    cost_per_unit: Decimal = Decimal("0.00")
    cost_per_purchase_unit: Optional[Decimal] = Decimal("0.00")
    primary_supplier_id: Optional[UUID] = None
    is_perishable: bool = False
    shelf_life_days: Optional[int] = None
    image_url: Optional[str] = None
    is_active: bool = True

class RestaurantIngredientCreate(RestaurantIngredientBase):
    outlet_id: Optional[UUID] = None

class RestaurantIngredientUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    sku: Optional[str] = None
    code: Optional[str] = None
    unit: Optional[str] = None
    purchase_uom: Optional[str] = None
    recipe_uom: Optional[str] = None
    uom_conversion_factor: Optional[Decimal] = None
    category_id: Optional[UUID] = None
    storage_zone: Optional[str] = None
    storage_location: Optional[str] = None
    current_stock: Optional[Decimal] = None
    reorder_level: Optional[Decimal] = None
    min_par_level: Optional[Decimal] = None
    ideal_par_level: Optional[Decimal] = None
    cost_per_unit: Optional[Decimal] = None
    cost_per_purchase_unit: Optional[Decimal] = None
    primary_supplier_id: Optional[UUID] = None
    is_perishable: Optional[bool] = None
    shelf_life_days: Optional[int] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None

class RestaurantIngredientResponse(RestaurantIngredientBase):
    id: UUID
    outlet_id: UUID
    tenant_id: UUID
    category_name: Optional[str] = None
    category_code: Optional[str] = None
    primary_supplier_name: Optional[str] = None
    is_negative_stock: bool = False
    last_restocked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "uom_conversion_factor", "current_stock", "reorder_level",
        "min_par_level", "ideal_par_level", "cost_per_unit",
        "cost_per_purchase_unit", check_fields=False
    )
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)



# Stock Ledger & Adjustments
class StockAdjustmentCreate(BaseModel):
    ingredient_id: UUID
    signed_quantity: Decimal # Positive for addition/surplus, Negative for wastage/deficit
    input_uom: Optional[str] = "RECIPE" # "PURCHASE" (e.g. KG) or "RECIPE" (e.g. GM)
    reason: str # PURCHASE_RECEIVED, WASTAGE, PHYSICAL_COUNT_ADJUSTMENT, SPOILAGE, BREAKAGE
    notes: Optional[str] = None

class WasteLogCreate(BaseModel):
    ingredient_id: UUID
    quantity: Decimal = Field(..., gt=0, description="Positive quantity wasted or spoiled")
    input_uom: Optional[str] = "RECIPE" # "PURCHASE" (e.g. KG) or "RECIPE" (e.g. G) or custom UOM
    waste_reason: str = Field("SPOILAGE", description="SPOILAGE, EXPIRY, PREP_LOSS, BURNT_RUINED, DROPPED_SPILL, QUALITY_REJECT")
    notes: Optional[str] = None

class DishWasteLogCreate(BaseModel):
    item_id: UUID
    outlet_id: Optional[UUID] = None
    variant_name: Optional[str] = "Standard"
    portions: Decimal = Field(Decimal("1.00"), gt=0, description="Number of prepared plates/portions discarded")
    waste_reason: str = Field("CUSTOMER_RETURN", description="CUSTOMER_RETURN, OVERCOOKED, DROPPED_SPILL, CANCELLED_AFTER_PREP")
    notes: Optional[str] = None

class StockLedgerResponse(BaseModel):
    id: UUID
    ingredient_id: UUID
    outlet_id: UUID
    tenant_id: UUID
    signed_quantity: Decimal
    unit_cost_at_time: Decimal = Decimal("0.0000")
    total_cost: Decimal = Decimal("0.00")
    reason: str
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    actor_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_at: datetime

    @field_serializer("signed_quantity", "unit_cost_at_time", "total_cost", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)


# Bulk Stock Audit Schemas
class StockAuditItemInput(BaseModel):
    ingredient_id: UUID
    physical_count: Decimal # Count observed during physical count
    input_uom: Optional[str] = "RECIPE" # "RECIPE" or "PURCHASE"
    expected_stock: Optional[Decimal] = None # System book stock snapshot when counting began
    notes: Optional[str] = None

class StockAuditBatchCreate(BaseModel):
    outlet_id: Optional[UUID] = None
    audit_date: Optional[date] = None
    audit_started_at: Optional[datetime] = None # When physical count sheet was opened
    notes: Optional[str] = None
    items: List[StockAuditItemInput]

class StockAuditItemResult(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    recipe_uom: str
    purchase_uom: str
    previous_stock: Decimal
    expected_stock: Optional[Decimal] = None
    physical_count: Decimal
    raw_input_count: Optional[Decimal] = None
    variance: Decimal # physical_count - previous_stock (in recipe unit)
    variance_rupees: Decimal # variance * unit_cost
    status: str # "MATCHED", "SURPLUS", "DEFICIT"
    notes: Optional[str] = None

    @field_serializer("previous_stock", "expected_stock", "physical_count", "raw_input_count", "variance", "variance_rupees", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

class StockAuditBatchResponse(BaseModel):
    audit_batch_id: str
    audit_date: date
    audit_started_at: Optional[datetime] = None
    outlet_id: UUID
    total_items_audited: int
    items_adjusted: int
    total_surplus_rupees: Decimal
    total_deficit_rupees: Decimal
    net_variance_rupees: Decimal
    notes: Optional[str] = None
    results: List[StockAuditItemResult]

    @field_serializer("total_surplus_rupees", "total_deficit_rupees", "net_variance_rupees", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

class StockAuditBatchSummary(BaseModel):
    audit_batch_id: str
    audit_date: date
    created_at: datetime
    outlet_id: UUID
    auditor_name: Optional[str] = "Manager / Auditor"
    items_adjusted: int
    total_surplus_rupees: Decimal
    total_deficit_rupees: Decimal
    net_variance_rupees: Decimal

    @field_serializer("total_surplus_rupees", "total_deficit_rupees", "net_variance_rupees", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None


# Recipe
from schemas.restaurant_stock_transfer import (
    StockTransferItemInput, StockTransferCreate, StockTransferDispatchInput,
    StockTransferReceiveItemInput, StockTransferReceiveInput,
    StockTransferItemResponse, StockTransferResponse
)

class RecipeLineInput(BaseModel):
    ingredient_id: UUID
    quantity_required: Decimal
    unit: Optional[str] = None # Auto-normalized to ingredient recipe_uom if None or different

class RecipeCreate(BaseModel):
    id: Optional[UUID] = None
    item_id: Optional[UUID] = None
    modifier_option_id: Optional[UUID] = None
    outlet_id: Optional[UUID] = None
    produced_ingredient_id: Optional[UUID] = None
    variant_name: str = "Standard"
    yield_servings: Decimal = Decimal("1.00")
    instructions: Optional[str] = None
    lines: List[RecipeLineInput] = []

class RecipeLineResponse(BaseModel):
    id: UUID
    ingredient_id: UUID
    ingredient_name: Optional[str] = None
    quantity_required: Decimal
    unit: str
    cost_per_unit: Optional[Decimal] = None
    line_cost: Optional[Decimal] = None

    @field_serializer("quantity_required", "cost_per_unit", "line_cost", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)

class RecipeResponse(BaseModel):
    id: UUID
    item_id: Optional[UUID] = None
    item_name: Optional[str] = None
    item_category: Optional[str] = None
    modifier_option_id: Optional[UUID] = None
    outlet_id: Optional[UUID] = None
    produced_ingredient_id: Optional[UUID] = None
    variant_name: str
    yield_servings: Decimal
    selling_price: Optional[Decimal] = None
    plate_cost: Optional[Decimal] = None
    food_cost_percentage: Optional[Decimal] = None
    gross_margin_percentage: Optional[Decimal] = None
    cost_status: Optional[str] = None
    instructions: Optional[str] = None
    lines: List[RecipeLineResponse] = []

    @field_serializer("yield_servings", "selling_price", "plate_cost", "food_cost_percentage", "gross_margin_percentage", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)

class RecipeLineCostBreakdown(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    quantity_required: Decimal
    unit: str
    portion_quantity: Decimal
    cost_per_unit: Decimal
    line_cost: Decimal
    cost_contribution_pct: Decimal

    @field_serializer("quantity_required", "portion_quantity", "cost_per_unit", "line_cost", "cost_contribution_pct", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

class RecipeCostingResponse(BaseModel):
    recipe_id: UUID
    item_id: Optional[UUID] = None
    item_name: str
    variant_name: str
    yield_servings: Decimal
    selling_price: Decimal
    plate_cost: Decimal
    food_cost_percentage: Decimal
    gross_margin_percentage: Decimal
    cost_status: str # "IDEAL" (<=30%), "WARNING" (30-35%), "CRITICAL_SPIKE" (>35%)
    breakdown: List[RecipeLineCostBreakdown] = []

    @field_serializer("yield_servings", "selling_price", "plate_cost", "food_cost_percentage", "gross_margin_percentage", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

