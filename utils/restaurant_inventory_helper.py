from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, Dict, Any, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func

from models.restaurant_ingredient import RestaurantIngredient
from models.restaurant_menu import RestaurantMenuItem, RestaurantItemPrice
from models.restaurant_recipe import RestaurantRecipe, RestaurantRecipeLine


def normalize_recipe_uom(
    quantity: Decimal,
    from_unit: Optional[str],
    target_uom: str,
    conversion_factor: Optional[Decimal] = None
) -> Tuple[Decimal, str]:
    """
    Safeguards against UOM mismatch between recipe line inputs and ingredient base recipe UOM.
    e.g. If a chef specifies 0.250 KG on an ingredient tracked in G, normalizes to 250.000 G.
    """
    tgt = (target_uom or "G").strip().upper()
    if not from_unit:
        return Decimal(str(quantity)), tgt

    src = from_unit.strip().upper()
    qty = Decimal(str(quantity))

    if src == tgt:
        return qty, tgt

    # Conversion factor from purchase unit to recipe unit
    conv = Decimal(str(conversion_factor or 1.0))
    if conv <= Decimal("0.0000"):
        conv = Decimal("1.0000")

    # Weight Conversions
    if src in ("KG", "KILOGRAM", "KGS") and tgt in ("G", "GM", "GRAM", "GRAMS"):
        return (qty * Decimal("1000")).quantize(Decimal("0.001")), tgt
    if src in ("G", "GM", "GRAM", "GRAMS") and tgt in ("KG", "KILOGRAM", "KGS"):
        return (qty / Decimal("1000")).quantize(Decimal("0.001")), tgt
    if src in ("MG", "MILLIGRAM") and tgt in ("G", "GM", "GRAM"):
        return (qty / Decimal("1000")).quantize(Decimal("0.001")), tgt

    # Volume Conversions
    if src in ("L", "LT", "LTR", "LITRE", "LITER") and tgt in ("ML", "MILLILITRE", "MILLILITER"):
        return (qty * Decimal("1000")).quantize(Decimal("0.001")), tgt
    if src in ("ML", "MILLILITRE", "MILLILITER") and tgt in ("L", "LT", "LTR", "LITRE", "LITER"):
        return (qty / Decimal("1000")).quantize(Decimal("0.001")), tgt

    # Quantity / Count Conversions
    if src in ("DOZEN", "DZ") and tgt in ("PCS", "PC", "UNIT", "UNITS", "PIECE", "PIECES"):
        return (qty * Decimal("12")).quantize(Decimal("0.001")), tgt

    # Custom conversion factor fallback
    if conv > Decimal("1.0000"):
        return (qty * conv).quantize(Decimal("0.001")), tgt

    return qty, tgt


def resolve_branch_ingredient(
    db: Session,
    base_ingredient: RestaurantIngredient,
    target_outlet_id: UUID
) -> RestaurantIngredient:
    """
    Resolves branch-specific ingredient for multi-branch chains.
    If a recipe or menu item was defined with Delhi 6's ingredient UUID,
    when Saltlake branch sells the dish, this resolves Saltlake's corresponding ingredient.
    """
    if not base_ingredient:
        return base_ingredient

    if base_ingredient.outlet_id == target_outlet_id:
        return base_ingredient

    # 1. Match by SKU in target outlet
    if base_ingredient.sku:
        by_sku = db.query(RestaurantIngredient).filter(
            RestaurantIngredient.outlet_id == target_outlet_id,
            RestaurantIngredient.sku == base_ingredient.sku,
            RestaurantIngredient.is_active == True
        ).first()
        if by_sku:
            return by_sku

    # 2. Match by normalized name and recipe_uom
    normalized_name = base_ingredient.name.strip().lower()
    by_name_uom = db.query(RestaurantIngredient).filter(
        RestaurantIngredient.outlet_id == target_outlet_id,
        func.lower(func.trim(RestaurantIngredient.name)) == normalized_name,
        RestaurantIngredient.recipe_uom == base_ingredient.recipe_uom,
        RestaurantIngredient.is_active == True
    ).first()
    if by_name_uom:
        return by_name_uom

    # 3. Match by normalized name alone
    by_name = db.query(RestaurantIngredient).filter(
        RestaurantIngredient.outlet_id == target_outlet_id,
        func.lower(func.trim(RestaurantIngredient.name)) == normalized_name,
        RestaurantIngredient.is_active == True
    ).first()
    if by_name:
        return by_name

    # Fallback to base ingredient
    return base_ingredient


def calculate_recipe_costing_data(
    recipe: RestaurantRecipe,
    db: Session,
    selling_price_override: Optional[Decimal] = None
) -> Dict[str, Any]:
    """
    Computes real-time plate food cost and gross margin % using Moving Weighted Average Cost (WAC).
    """
    # 1. Determine menu selling price
    selling_price = Decimal("0.00")
    item_name = "Custom Dish / Prep"

    if recipe.item_id:
        menu_item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == recipe.item_id).first()
        if menu_item:
            item_name = menu_item.name
            if selling_price_override is not None:
                selling_price = Decimal(str(selling_price_override))
            else:
                # Check variant price
                variant_price = (
                    db.query(RestaurantItemPrice)
                    .filter(
                        RestaurantItemPrice.item_id == menu_item.id,
                        RestaurantItemPrice.variant_name == recipe.variant_name
                    )
                    .first()
                )
                if variant_price and variant_price.price is not None:
                    selling_price = Decimal(str(variant_price.price))
                elif menu_item.price is not None:
                    selling_price = Decimal(str(menu_item.price))

    yield_val = Decimal(str(recipe.yield_servings or 1.00))
    if yield_val <= Decimal("0.00"):
        yield_val = Decimal("1.00")

    total_plate_cost = Decimal("0.00")
    breakdown: List[Dict[str, Any]] = []

    for r_line in (recipe.lines or []):
        ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == r_line.ingredient_id).first()
        ing_name = ing.name if ing else "Unknown Ingredient"
        cost_per_uom = Decimal(str(ing.cost_per_unit or 0.00)) if ing else Decimal("0.00")

        # Portion required for 1 serving
        portion_qty = (Decimal(str(r_line.quantity_required)) / yield_val).quantize(Decimal("0.001"))
        line_cost = (portion_qty * cost_per_uom).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_plate_cost += line_cost

        breakdown.append({
            "ingredient_id": r_line.ingredient_id,
            "ingredient_name": ing_name,
            "quantity_required": Decimal(str(r_line.quantity_required)),
            "unit": r_line.unit,
            "portion_quantity": portion_qty,
            "cost_per_unit": cost_per_uom,
            "line_cost": line_cost,
            "cost_contribution_pct": Decimal("0.00") # Calculated below
        })

    # Calculate contribution percentage of each ingredient
    for item in breakdown:
        if total_plate_cost > Decimal("0.00"):
            item["cost_contribution_pct"] = (
                (item["line_cost"] / total_plate_cost) * Decimal("100.00")
            ).quantize(Decimal("0.1"))
        else:
            item["cost_contribution_pct"] = Decimal("0.0")

    # Food Cost % & Margins
    food_cost_pct = Decimal("0.00")
    if selling_price > Decimal("0.00"):
        food_cost_pct = ((total_plate_cost / selling_price) * Decimal("100.00")).quantize(Decimal("0.1"))

    gross_margin_pct = (Decimal("100.00") - food_cost_pct).quantize(Decimal("0.1"))

    # Cost Status threshold flagging
    if food_cost_pct <= Decimal("30.0"):
        cost_status = "IDEAL"
    elif food_cost_pct <= Decimal("35.0"):
        cost_status = "WARNING"
    else:
        cost_status = "CRITICAL_SPIKE"

    return {
        "recipe_id": recipe.id,
        "item_id": recipe.item_id,
        "item_name": item_name,
        "variant_name": recipe.variant_name,
        "yield_servings": yield_val,
        "selling_price": selling_price,
        "plate_cost": total_plate_cost,
        "food_cost_percentage": food_cost_pct,
        "gross_margin_percentage": gross_margin_pct,
        "cost_status": cost_status,
        "breakdown": breakdown
    }
