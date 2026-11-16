from typing import Optional, List
from uuid import UUID
from datetime import datetime
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
    is_active: Optional[bool] = None

class RestaurantIngredientResponse(RestaurantIngredientBase):
    id: UUID
    outlet_id: UUID
    tenant_id: UUID
    category_name: Optional[str] = None
    category_code: Optional[str] = None
    primary_supplier_name: Optional[str] = None
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



# Stock Ledger
class StockAdjustmentCreate(BaseModel):
    ingredient_id: UUID
    signed_quantity: Decimal # Positive for addition, Negative for wastage
    reason: str # PURCHASE_RECEIVED, WASTAGE, PHYSICAL_COUNT_ADJUSTMENT
    notes: Optional[str] = None

class StockLedgerResponse(BaseModel):
    id: UUID
    ingredient_id: UUID
    outlet_id: UUID
    tenant_id: UUID
    signed_quantity: Decimal
    reason: str
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    actor_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Recipe
class RecipeLineInput(BaseModel):
    ingredient_id: UUID
    quantity_required: Decimal
    unit: str

class RecipeCreate(BaseModel):
    item_id: UUID
    variant_name: str = "Standard"
    yield_servings: Decimal = Decimal("1.00")
    instructions: Optional[str] = None
    lines: List[RecipeLineInput] = []

class RecipeLineResponse(BaseModel):
    id: UUID
    ingredient_id: UUID
    quantity_required: Decimal
    unit: str

    model_config = ConfigDict(from_attributes=True)

class RecipeResponse(BaseModel):
    id: UUID
    item_id: UUID
    variant_name: str
    yield_servings: Decimal
    instructions: Optional[str] = None
    lines: List[RecipeLineResponse] = []

    model_config = ConfigDict(from_attributes=True)
