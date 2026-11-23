from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import datetime, date
import os
import shutil
import uuid
import re
import urllib.request
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_ingredient import RestaurantIngredient, RestaurantIngredientCategory
from models.restaurant_menu import RestaurantMenuItem, RestaurantMenuCategory
from models.restaurant_recipe import RestaurantRecipe
from models.restaurant_stock_ledger import RestaurantStockLedger
from models.restaurant_stock_audit import RestaurantStockAudit, RestaurantStockAuditItem
from models.restaurant_order import RestaurantOrder
from schemas.restaurant_inventory import (
    RestaurantIngredientCategoryCreate, RestaurantIngredientCategoryUpdate, RestaurantIngredientCategoryResponse,
    RestaurantIngredientCreate, RestaurantIngredientUpdate, RestaurantIngredientResponse,
    StockAdjustmentCreate, StockLedgerResponse,
    WasteLogCreate, DishWasteLogCreate,
    StockAuditBatchCreate, StockAuditBatchResponse, StockAuditItemResult, StockAuditBatchSummary,
    RecipeCreate, RecipeResponse, RecipeCostingResponse
)
from utils.restaurant_inventory_helper import normalize_recipe_uom, calculate_recipe_costing_data, resolve_branch_ingredient
from dependencies import get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff
from utils.timezone import get_current_time, get_current_date

router = APIRouter(
    prefix="/api/restaurant/inventory",
    tags=["Restaurant - Ingredients & Recipes"]
)

def resolve_outlet(db: Session, outlet_id: Optional[UUID] = None) -> RestaurantOutlet:
    """
    Resolves target outlet. If outlet_id is not passed, falls back to first active outlet.
    Ensures data is strictly isolated to that specific branch.
    """
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

def generate_unique_category_code(db: Session, outlet_id: UUID, name: str) -> str:
    """
    Intelligently auto-generate a clean, concise category code (e.g. DRY, DAIRY, MEAT, PRODUCE, SPICE, BAR).
    Guarantees uniqueness within the specific branch/outlet.
    """
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower()
    words = cleaned.split()

    # Intelligent food & kitchen keyword mappings for best restaurant UX
    keyword_map = [
        (["dry", "grain", "pantry", "flour", "rice", "dal", "pulses", "lentil"], "DRY"),
        (["dairy", "cheese", "milk", "butter", "paneer", "curd", "cream", "yogurt"], "DAIRY"),
        (["meat", "poultry", "chicken", "mutton", "lamb", "beef", "pork"], "MEAT"),
        (["produce", "vegetable", "veggie", "herb", "fresh", "onion", "tomato", "salad"], "PRODUCE"),
        (["spice", "oil", "condiment", "masala", "sauce", "seasoning", "vinegar"], "SPICE"),
        (["bar", "beverage", "drink", "liquor", "juice", "soda", "wine", "beer"], "BAR"),
        (["seafood", "fish", "prawn", "crab", "shrimp"], "SEAFOOD"),
        (["bakery", "bread", "bun", "pastry", "cake"], "BAKERY"),
        (["frozen", "freezer", "ice", "dessert"], "FROZEN"),
    ]

    base_code = None
    for keywords, code in keyword_map:
        if any(kw in cleaned for kw in keywords):
            base_code = code
            break

    if not base_code:
        if not words:
            base_code = "CAT"
        elif len(words) == 1:
            base_code = words[0][:5].upper()
        else:
            first_w = words[0].upper()
            if 3 <= len(first_w) <= 6:
                base_code = first_w
            else:
                base_code = "".join([w[0].upper() for w in words[:4]])

    if not base_code:
        base_code = "CAT"

    # Enforce uniqueness within the outlet
    candidate = base_code
    counter = 1
    while True:
        existing = db.query(RestaurantIngredientCategory).filter(
            RestaurantIngredientCategory.outlet_id == outlet_id,
            RestaurantIngredientCategory.code == candidate,
            RestaurantIngredientCategory.is_active == True
        ).first()
        if not existing:
            return candidate
        counter += 1
        candidate = f"{base_code}{counter}"


# ----------------- INGREDIENT CATEGORIES & STORAGE ZONES -----------------

@router.get("/categories/generate-code")
def preview_category_code(
    name: str = Query(..., description="Category name to generate code for"),
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Helper endpoint for UI: Auto-generates and displays the unique category code
    in real time as the user types the category name in the modal.
    """
    outlet = resolve_outlet(db, outlet_id)
    generated_code = generate_unique_category_code(db, outlet.id, name)
    return {
        "name": name,
        "code": generated_code,
        "outlet_id": outlet.id
    }


@router.get("/categories", response_model=List[RestaurantIngredientCategoryResponse])
def get_ingredient_categories(
    outlet_id: Optional[UUID] = None,
    search: Optional[str] = Query(None, description="Search by name, code, or storage zone"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Fetch ingredient categories and storage zones for a specific branch.
    Strictly isolated by outlet_id & tenant_id so branches never mix.
    Includes active items_count per category.
    """
    outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantIngredientCategory)
        .filter(RestaurantIngredientCategory.outlet_id == outlet.id)
        .filter(RestaurantIngredientCategory.is_active == True)
    )

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        search_pattern = f"%{search_str}%"
        query = query.filter(
            or_(
                RestaurantIngredientCategory.name.ilike(search_pattern),
                RestaurantIngredientCategory.code.ilike(search_pattern),
                RestaurantIngredientCategory.storage_zone_temp.ilike(search_pattern)
            )
        )

    categories = query.order_by(
        RestaurantIngredientCategory.sort_order.asc(),
        RestaurantIngredientCategory.name.asc()
    ).all()

    # Calculate items count per category for this outlet in a single aggregate query
    counts_subquery = (
        db.query(
            RestaurantIngredient.category_id,
            func.count(RestaurantIngredient.id).label("count")
        )
        .filter(
            RestaurantIngredient.outlet_id == outlet.id,
            RestaurantIngredient.is_active == True
        )
        .group_by(RestaurantIngredient.category_id)
        .all()
    )
    counts_map = {row[0]: row[1] for row in counts_subquery if row[0] is not None}

    results = []
    for cat in categories:
        cat_dict = {
            "id": cat.id,
            "outlet_id": cat.outlet_id,
            "tenant_id": cat.tenant_id,
            "name": cat.name,
            "code": cat.code,
            "storage_zone_temp": cat.storage_zone_temp,
            "color_code": cat.color_code,
            "icon": cat.icon,
            "description": cat.description,
            "sort_order": cat.sort_order,
            "is_active": cat.is_active,
            "items_count": counts_map.get(cat.id, 0),
            "created_at": cat.created_at,
            "updated_at": cat.updated_at
        }
        results.append(RestaurantIngredientCategoryResponse(**cat_dict))

    return results


@router.post("/categories", response_model=RestaurantIngredientCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_ingredient_category(
    payload: RestaurantIngredientCategoryCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Create an ingredient storage category / zone for the branch.
    Guarantees strict branch & tenant isolation using outlet.tenant_id.
    """
    outlet = resolve_outlet(db, payload.outlet_id)

    # Auto-generate unique category code if not supplied or empty
    code = payload.code.strip().upper() if payload.code and payload.code.strip() else None
    if not code:
        code = generate_unique_category_code(db, outlet.id, payload.name)

    category = RestaurantIngredientCategory(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        name=payload.name.strip(),
        code=code,
        storage_zone_temp=payload.storage_zone_temp.strip() if payload.storage_zone_temp else None,
        color_code=payload.color_code or "#F59E0B",
        icon=payload.icon,
        description=payload.description,
        sort_order=payload.sort_order,
        is_active=payload.is_active
    )
    db.add(category)
    db.commit()
    db.refresh(category)

    res = RestaurantIngredientCategoryResponse.model_validate(category)
    res.items_count = 0
    return res


@router.get("/categories/{category_id}", response_model=RestaurantIngredientCategoryResponse)
def get_ingredient_category_by_id(
    category_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    category = db.query(RestaurantIngredientCategory).filter(RestaurantIngredientCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    items_count = (
        db.query(func.count(RestaurantIngredient.id))
        .filter(
            RestaurantIngredient.category_id == category.id,
            RestaurantIngredient.is_active == True
        )
        .scalar() or 0
    )

    res = RestaurantIngredientCategoryResponse.model_validate(category)
    res.items_count = items_count
    return res


@router.put("/categories/{category_id}", response_model=RestaurantIngredientCategoryResponse)
@router.patch("/categories/{category_id}", response_model=RestaurantIngredientCategoryResponse)
def update_ingredient_category(
    category_id: UUID,
    payload: RestaurantIngredientCategoryUpdate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    category = db.query(RestaurantIngredientCategory).filter(RestaurantIngredientCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "code" in update_data and update_data["code"]:
        update_data["code"] = update_data["code"].strip().upper()

    for field, value in update_data.items():
        setattr(category, field, value)

    db.commit()
    db.refresh(category)

    items_count = (
        db.query(func.count(RestaurantIngredient.id))
        .filter(
            RestaurantIngredient.category_id == category.id,
            RestaurantIngredient.is_active == True
        )
        .scalar() or 0
    )

    res = RestaurantIngredientCategoryResponse.model_validate(category)
    res.items_count = items_count
    return res


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingredient_category(
    category_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Delete category from DB. Unlinks associated ingredients.
    """
    category = db.query(RestaurantIngredientCategory).filter(RestaurantIngredientCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Ingredient category not found")

    # Unlink ingredients from this category
    db.query(RestaurantIngredient).filter(RestaurantIngredient.category_id == category.id).update(
        {"category_id": None}, synchronize_session=False
    )
    db.delete(category)
    db.commit()
    return None


@router.post("/categories/seed-defaults", response_model=List[RestaurantIngredientCategoryResponse])
def seed_default_ingredient_categories(
    outlet_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Convenience endpoint to initialize default restaurant storage categories:
    - Dry & Grain Pantry (Ambient Store Shelf A-C)
    - Dairy & Cheese (Walk-in Chiller 2-4°C)
    - Meat & Poultry (Deep Freezer -18°C)
    - Fresh Vegetables & Herbs (Vegetable Chiller 6-8°C)
    - Spices, Oils & Condiments (Ambient Spice Rack)
    - Beverage & Bar Stocks (Bar Cellar Room)
    """
    outlet = resolve_outlet(db, outlet_id)

    # Check if categories already exist
    existing = db.query(RestaurantIngredientCategory).filter(
        RestaurantIngredientCategory.outlet_id == outlet.id,
        RestaurantIngredientCategory.is_active == True
    ).first()
    if existing:
        return get_ingredient_categories(outlet_id=outlet.id, search=None, db=db, current_user=manager_user)

    defaults = [
        {"name": "Dry & Grain Pantry", "code": "DRY", "storage_zone_temp": "Ambient Store (Shelf A-C)", "color_code": "#F59E0B", "sort_order": 1},
        {"name": "Dairy & Cheese", "code": "DAIRY", "storage_zone_temp": "Walk-in Chiller (2°C - 4°C)", "color_code": "#3B82F6", "sort_order": 2},
        {"name": "Meat & Poultry", "code": "MEAT", "storage_zone_temp": "Deep Freezer (-18°C)", "color_code": "#EF4444", "sort_order": 3},
        {"name": "Fresh Vegetables & Herbs", "code": "PRODUCE", "storage_zone_temp": "Vegetable Chiller (6°C - 8°C)", "color_code": "#10B981", "sort_order": 4},
        {"name": "Spices, Oils & Condiments", "code": "SPICE", "storage_zone_temp": "Ambient Spice Rack", "color_code": "#F97316", "sort_order": 5},
        {"name": "Beverage & Bar Stocks", "code": "BAR", "storage_zone_temp": "Bar Cellar Room", "color_code": "#8B5CF6", "sort_order": 6},
    ]

    for item in defaults:
        cat = RestaurantIngredientCategory(
            outlet_id=outlet.id,
            tenant_id=outlet.tenant_id,
            name=item["name"],
            code=item["code"],
            storage_zone_temp=item["storage_zone_temp"],
            color_code=item["color_code"],
            sort_order=item["sort_order"],
            is_active=True
        )
        db.add(cat)

    db.commit()
    return get_ingredient_categories(outlet_id=outlet.id, search=None, db=db, current_user=manager_user)


# ----------------- INGREDIENTS -----------------

@router.get("/ingredients", response_model=List[RestaurantIngredientResponse])
def get_ingredients(
    outlet_id: Optional[UUID] = None,
    category_id: Optional[UUID] = None,
    low_stock_only: bool = False,
    search: Optional[str] = Query(None, description="Search by name, SKU, or storage zone"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Fetch raw ingredients for an outlet with complete master fields.
    Strictly isolated by outlet_id so branch stocks never get mixed up.
    """
    outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantIngredient)
        .options(
            joinedload(RestaurantIngredient.category),
            joinedload(RestaurantIngredient.supplier)
        )
        .filter(RestaurantIngredient.outlet_id == outlet.id)
        .filter(RestaurantIngredient.is_active == True)
    )

    if category_id:
        query = query.filter(RestaurantIngredient.category_id == category_id)

    search_str = search.strip() if isinstance(search, str) and search.strip() else None
    if search_str:
        search_pattern = f"%{search_str}%"
        query = query.filter(
            or_(
                RestaurantIngredient.name.ilike(search_pattern),
                RestaurantIngredient.sku.ilike(search_pattern),
                RestaurantIngredient.storage_zone.ilike(search_pattern),
                RestaurantIngredient.storage_location.ilike(search_pattern)
            )
        )

    if low_stock_only:
        query = query.filter(
            or_(
                RestaurantIngredient.current_stock <= RestaurantIngredient.reorder_level,
                RestaurantIngredient.current_stock <= RestaurantIngredient.min_par_level
            )
        )

    ingredients = query.order_by(RestaurantIngredient.name.asc()).all()

    # Format response with category and supplier helper fields
    results = []
    for ing in ingredients:
        res = RestaurantIngredientResponse.model_validate(ing)
        res.code = ing.sku
        res.storage_location = ing.storage_location or ing.storage_zone
        res.storage_zone = ing.storage_zone or ing.storage_location
        res.is_negative_stock = bool((ing.current_stock or Decimal("0.000")) < Decimal("0.000"))
        if ing.category:
            res.category_name = ing.category.name
            res.category_code = ing.category.code
        if ing.supplier:
            res.primary_supplier_name = ing.supplier.name
        results.append(res)

    return results


@router.post("/ingredients/upload-image")
async def upload_ingredient_image(
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Upload an ingredient image file. Stores in uploads/inventory/ and returns the relative path URL.
    """
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    os.makedirs("uploads/inventory", exist_ok=True)
    orig_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"
    ext = orig_ext if orig_ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else ".jpg"
    filename = f"ing_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join("uploads", "inventory", filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"image_url": f"/uploads/inventory/{filename}"}


@router.post("/ingredients/upload-from-url")
def upload_ingredient_from_url(
    payload: dict,
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Downloads an image from an external URL, saves it into uploads/inventory/
    and returns {"image_url": "/uploads/inventory/ing_...jpg"}.
    This completely eliminates CORS issues and ensures the ingredient image is hosted locally.
    """
    raw_url = payload.get("url", "").strip() if isinstance(payload, dict) else ""
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL. Must begin with http:// or https://")

    try:
        req = urllib.request.Request(
            raw_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content_type = response.headers.get("content-type", "image/jpeg").lower()
            data = response.read()

        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif "gif" in content_type:
            ext = ".gif"
        elif ".png" in raw_url.lower():
            ext = ".png"
        elif ".webp" in raw_url.lower():
            ext = ".webp"

        os.makedirs("uploads/inventory", exist_ok=True)
        filename = f"ing_{uuid.uuid4().hex[:12]}{ext}"
        file_path = os.path.join("uploads", "inventory", filename)

        with open(file_path, "wb") as f:
            f.write(data)

        return {"image_url": f"/uploads/inventory/{filename}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download image from link: {str(e)}")


@router.api_route("/proxy-image", methods=["GET", "HEAD"])
def proxy_external_image(url: str = Query(..., description="External image URL to proxy for CORS")):
    """
    Proxies external images to bypass browser CORS restrictions in Flutter Web.
    Caches images locally in uploads/inventory/cache/ for fast subsequent loads.
    """
    clean_url = url.strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL protocol")

    url_hash = hashlib.md5(clean_url.encode("utf-8")).hexdigest()
    cache_dir = os.path.join("uploads", "inventory", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{url_hash}.bin")
    meta_path = os.path.join(cache_dir, f"{url_hash}.meta")

    if os.path.exists(cache_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                content_type = f.read().strip() or "image/jpeg"
            with open(cache_path, "rb") as f:
                return Response(
                    content=f.read(),
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=604800",
                        "Access-Control-Allow-Origin": "*",
                    }
                )
        except Exception:
            pass

    try:
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            content_type = response.headers.get("content-type", "image/jpeg")
            image_data = response.read()

            try:
                with open(cache_path, "wb") as f:
                    f.write(image_data)
                with open(meta_path, "w") as f:
                    f.write(content_type)
            except Exception:
                pass

            return Response(
                content=image_data,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=604800",
                    "Access-Control-Allow-Origin": "*",
                }
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch image: {str(e)}")


@router.post("/ingredients", response_model=RestaurantIngredientResponse, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: RestaurantIngredientCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Create a new ingredient for a branch storing all fields in DB:
    name, sku/code, category_id, supplier, dual-UOM (purchase & recipe),
    conversion factor, min & ideal par levels, costs, storage location, perishability.
    Guarantees strict tenant & branch isolation.
    """
    outlet = resolve_outlet(db, payload.outlet_id)

    # Validate category belongs to this branch if provided
    if payload.category_id:
        category = db.query(RestaurantIngredientCategory).filter(
            RestaurantIngredientCategory.id == payload.category_id,
            RestaurantIngredientCategory.outlet_id == outlet.id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail="Selected category does not exist or belongs to another branch"
            )

    sku_val = (payload.sku or payload.code or "").strip()
    storage_val = (payload.storage_location or payload.storage_zone or "").strip() or None
    recipe_uom_val = (payload.recipe_uom or payload.unit or "G").strip().upper()
    purchase_uom_val = (payload.purchase_uom or "KG").strip().upper()
    conv_factor = Decimal(str(payload.uom_conversion_factor or 1.0))
    min_par = Decimal(str(payload.min_par_level if payload.min_par_level is not None else payload.reorder_level))
    ideal_par = Decimal(str(payload.ideal_par_level or 0.0))
    cost_purchase = Decimal(str(payload.cost_per_purchase_unit or 0.0))
    
    # Calculate base recipe cost per unit
    if conv_factor > 0 and cost_purchase > 0:
        cost_unit = (cost_purchase / conv_factor).quantize(Decimal("0.01"))
    else:
        cost_unit = Decimal(str(payload.cost_per_unit or 0.0))

    ingredient = RestaurantIngredient(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        category_id=payload.category_id,
        primary_supplier_id=payload.primary_supplier_id,
        name=payload.name.strip(),
        sku=sku_val if sku_val else None,
        unit=recipe_uom_val,
        purchase_uom=purchase_uom_val,
        recipe_uom=recipe_uom_val,
        uom_conversion_factor=conv_factor,
        min_par_level=min_par,
        reorder_level=min_par,
        ideal_par_level=ideal_par,
        cost_per_purchase_unit=cost_purchase,
        cost_per_unit=cost_unit,
        storage_zone=storage_val,
        storage_location=storage_val,
        is_perishable=payload.is_perishable,
        shelf_life_days=payload.shelf_life_days,
        current_stock=payload.current_stock,
        image_url=payload.image_url,
        is_active=payload.is_active
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)

    res = RestaurantIngredientResponse.model_validate(ingredient)
    res.code = ingredient.sku
    res.storage_location = ingredient.storage_location or ingredient.storage_zone
    res.storage_zone = ingredient.storage_zone or ingredient.storage_location
    if ingredient.category:
        res.category_name = ingredient.category.name
        res.category_code = ingredient.category.code
    if ingredient.supplier:
        res.primary_supplier_name = ingredient.supplier.name
    return res


@router.get("/ingredients/{ingredient_id}", response_model=RestaurantIngredientResponse)
def get_ingredient_by_id(
    ingredient_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    ingredient = (
        db.query(RestaurantIngredient)
        .options(
            joinedload(RestaurantIngredient.category),
            joinedload(RestaurantIngredient.supplier)
        )
        .filter(RestaurantIngredient.id == ingredient_id)
        .first()
    )
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    res = RestaurantIngredientResponse.model_validate(ingredient)
    res.code = ingredient.sku
    res.storage_location = ingredient.storage_location or ingredient.storage_zone
    res.storage_zone = ingredient.storage_zone or ingredient.storage_location
    if ingredient.category:
        res.category_name = ingredient.category.name
        res.category_code = ingredient.category.code
    if ingredient.supplier:
        res.primary_supplier_name = ingredient.supplier.name
    return res


@router.put("/ingredients/{ingredient_id}", response_model=RestaurantIngredientResponse)
@router.patch("/ingredients/{ingredient_id}", response_model=RestaurantIngredientResponse)
def update_ingredient(
    ingredient_id: UUID,
    payload: RestaurantIngredientUpdate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    ingredient = (
        db.query(RestaurantIngredient)
        .options(
            joinedload(RestaurantIngredient.category),
            joinedload(RestaurantIngredient.supplier)
        )
        .filter(RestaurantIngredient.id == ingredient_id)
        .first()
    )
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Validate category belongs to this branch if category_id is being changed
    if "category_id" in update_data and update_data["category_id"] is not None:
        category = db.query(RestaurantIngredientCategory).filter(
            RestaurantIngredientCategory.id == update_data["category_id"],
            RestaurantIngredientCategory.outlet_id == ingredient.outlet_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail="Selected category does not exist or belongs to another branch"
            )

    # Handle alias mappings
    if "code" in update_data and update_data["code"]:
        update_data["sku"] = update_data["code"].strip()
    if "sku" in update_data and update_data["sku"]:
        update_data["sku"] = update_data["sku"].strip()

    if "recipe_uom" in update_data and update_data["recipe_uom"]:
        update_data["recipe_uom"] = update_data["recipe_uom"].upper()
        update_data["unit"] = update_data["recipe_uom"]
    elif "unit" in update_data and update_data["unit"]:
        update_data["unit"] = update_data["unit"].upper()
        update_data["recipe_uom"] = update_data["unit"]

    if "purchase_uom" in update_data and update_data["purchase_uom"]:
        update_data["purchase_uom"] = update_data["purchase_uom"].upper()

    if "storage_location" in update_data:
        update_data["storage_zone"] = update_data["storage_location"]
    elif "storage_zone" in update_data:
        update_data["storage_location"] = update_data["storage_zone"]

    if "min_par_level" in update_data and update_data["min_par_level"] is not None:
        update_data["reorder_level"] = update_data["min_par_level"]
    elif "reorder_level" in update_data and update_data["reorder_level"] is not None:
        update_data["min_par_level"] = update_data["reorder_level"]

    for field, value in update_data.items():
        if hasattr(ingredient, field):
            setattr(ingredient, field, value)

    # Auto-recalculate cost_per_unit if purchase cost or conversion factor changed
    conv = ingredient.uom_conversion_factor or Decimal("1.0")
    cost_p = ingredient.cost_per_purchase_unit or Decimal("0.0")
    if conv > 0 and cost_p > 0:
        ingredient.cost_per_unit = (cost_p / conv).quantize(Decimal("0.01"))

    db.commit()
    db.refresh(ingredient)

    res = RestaurantIngredientResponse.model_validate(ingredient)
    res.code = ingredient.sku
    res.storage_location = ingredient.storage_location or ingredient.storage_zone
    res.storage_zone = ingredient.storage_zone or ingredient.storage_location
    if ingredient.category:
        res.category_name = ingredient.category.name
        res.category_code = ingredient.category.code
    if ingredient.supplier:
        res.primary_supplier_name = ingredient.supplier.name
    return res


@router.delete("/ingredients/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingredient(
    ingredient_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Permanently delete ingredient row from the database.
    """
    ingredient = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    db.delete(ingredient)
    db.commit()
    return None


@router.post("/adjustments", response_model=StockLedgerResponse, status_code=status.HTTP_201_CREATED)
def record_stock_adjustment(
    payload: StockAdjustmentCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Append-only stock ledger adjustment. Modifies current stock balance atomically:
    1. Acquires SELECT ... FOR UPDATE row-level lock on the ingredient.
    2. Handles chef unit ergonomics (converts from PURCHASE UOM e.g. KG -> recipe GM if input_uom == 'PURCHASE').
    3. Snapshots unit_cost_at_time and calculates total_cost for exact historical rupee audit.
    4. Evaluates outlet negative stock policy.
    """
    ingredient = db.query(RestaurantIngredient).filter(
        RestaurantIngredient.id == payload.ingredient_id
    ).with_for_update().first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == ingredient.outlet_id).first()
    raw_qty = Decimal(str(payload.signed_quantity))

    # Unit ergonomics: Determine whether chef entered in PURCHASE unit (KG, LTR) or RECIPE unit (GM, ML)
    input_uom = (payload.input_uom or "RECIPE").strip().upper()
    purch_uom = (ingredient.purchase_uom or "").strip().upper()
    recipe_uom = (ingredient.recipe_uom or ingredient.unit or "").strip().upper()
    conversion = Decimal(str(ingredient.uom_conversion_factor or 1.0))
    if conversion <= Decimal("0.0000"):
        conversion = Decimal("1.0000")

    if input_uom in ("PURCHASE", purch_uom) and purch_uom != recipe_uom:
        signed_qty = round(raw_qty * conversion, 3)
        unit_label = f"{raw_qty} {purch_uom} ({signed_qty} {recipe_uom})"
    else:
        signed_qty = raw_qty
        unit_label = f"{signed_qty} {recipe_uom}"

    # Negative stock guard policy check
    new_stock = (ingredient.current_stock or Decimal("0.000")) + signed_qty
    if new_stock < Decimal("0.000") and outlet and not getattr(outlet, "allow_negative_stock", True):
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment of {unit_label} would result in negative stock ({new_stock} {recipe_uom}). Negative stock is disabled for this outlet."
        )

    actor_id = manager_user.id if manager_user else None
    unit_cost = ingredient.cost_per_unit or Decimal("0.0000")
    total_cost_val = round(abs(signed_qty) * unit_cost, 2)

    ledger_entry = RestaurantStockLedger(
        ingredient_id=ingredient.id,
        outlet_id=ingredient.outlet_id,
        tenant_id=ingredient.tenant_id,
        signed_quantity=signed_qty,
        unit_cost_at_time=unit_cost,
        total_cost=total_cost_val,
        reason=payload.reason.strip().upper(),
        source_type="manual_adjustment",
        source_id=f"ADJ-{get_current_time().strftime('%Y%m%d%H%M%S')}",
        actor_id=actor_id,
        notes=f"{payload.notes or 'Manual adjustment'} [Entered: {unit_label}]"
    )
    db.add(ledger_entry)

    # Atomically adjust current cached balance
    ingredient.current_stock += signed_qty
    ingredient.last_restocked_at = get_current_time()

    db.commit()
    db.refresh(ledger_entry)
    return ledger_entry


@router.post("/audits/submit", response_model=StockAuditBatchResponse, status_code=status.HTTP_201_CREATED)
def submit_stock_audit(
    payload: StockAuditBatchCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Bulk Physical Stock Audit submission:
    1. Deadlock Guard: Sorts ingredient_ids ascending before acquiring SELECT ... FOR UPDATE row locks.
    2. Shift Drift Detection: Identifies intervening POS sales/movements between count start and submit.
    3. Audit History Preservation: Creates RestaurantStockAudit and RestaurantStockAuditItem records
       for ALL items (including zero-variance MATCHED items).
    4. Append-Only Ledger: Writes PHYSICAL_COUNT_ADJUSTMENT entries only when variance != 0.
    5. Clean Inventory Master: Updates current_stock without corrupting last_restocked_at.
    """
    outlet = resolve_outlet(db, payload.outlet_id)
    audit_date = payload.audit_date or get_current_date()
    batch_code = f"AUDIT-{get_current_time().strftime('%Y%m%d-%H%M%S')}"

    # Guard 4: Sort items ascending by ingredient_id to guarantee deterministic row locking order
    sorted_items = sorted(payload.items, key=lambda item: str(item.ingredient_id))

    # Audit header persistence
    audit_record = RestaurantStockAudit(
        batch_code=batch_code,
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        auditor_id=manager_user.id if manager_user else None,
        audit_date=audit_date,
        audit_started_at=payload.audit_started_at,
        notes=payload.notes,
        total_items_audited=len(sorted_items),
        items_adjusted=0,
        total_surplus_rupees=Decimal("0.00"),
        total_deficit_rupees=Decimal("0.00"),
        net_variance_rupees=Decimal("0.00")
    )
    db.add(audit_record)
    db.flush()

    results = []
    items_adjusted = 0
    total_surplus_rupees = Decimal("0.00")
    total_deficit_rupees = Decimal("0.00")

    for item_input in sorted_items:
        ing = db.query(RestaurantIngredient).filter(
            RestaurantIngredient.id == item_input.ingredient_id,
            RestaurantIngredient.outlet_id == outlet.id
        ).with_for_update().first()

        if not ing:
            raise HTTPException(status_code=400, detail=f"Ingredient {item_input.ingredient_id} not found in this outlet")

        conversion = Decimal(str(ing.uom_conversion_factor or 1.0))
        if conversion <= Decimal("0.0000"):
            conversion = Decimal("1.0000")

        input_uom = (item_input.input_uom or "RECIPE").strip().upper()
        purch_uom = (ing.purchase_uom or "").strip().upper()
        recipe_uom = (ing.recipe_uom or ing.unit or "").strip().upper()

        raw_count = Decimal(str(item_input.physical_count))
        if input_uom in ("PURCHASE", purch_uom) and purch_uom != recipe_uom:
            physical_count_recipe = round(raw_count * conversion, 3)
        else:
            physical_count_recipe = raw_count

        prev_stock = ing.current_stock or Decimal("0.000")
        variance = physical_count_recipe - prev_stock
        unit_cost = ing.cost_per_unit or Decimal("0.0000")
        variance_rupees = round(variance * unit_cost, 2)

        # Guard 1: Detect Book Drift during active counting window
        drift_note = None
        if item_input.expected_stock is not None and item_input.expected_stock != prev_stock:
            since_time = payload.audit_started_at or get_current_time().replace(hour=0, minute=0, second=0)
            shift_movement = db.query(func.coalesce(func.sum(RestaurantStockLedger.signed_quantity), 0)).filter(
                RestaurantStockLedger.ingredient_id == ing.id,
                RestaurantStockLedger.outlet_id == outlet.id,
                RestaurantStockLedger.created_at >= since_time
            ).scalar()
            drift_note = f"Shift drift: Count sheet opened with {item_input.expected_stock} {recipe_uom}, live stock at submit was {prev_stock} {recipe_uom} (Intervening movements: {shift_movement:+} {recipe_uom})"

        item_notes = item_input.notes
        if drift_note:
            item_notes = f"{item_notes} | {drift_note}" if item_notes else drift_note

        if variance > Decimal("0.000"):
            status_label = "SURPLUS"
            total_surplus_rupees += variance_rupees
        elif variance < Decimal("0.000"):
            status_label = "DEFICIT"
            total_deficit_rupees += abs(variance_rupees)
        else:
            status_label = "MATCHED"

        # Guard 2: Always save full audit proof for MATCHED, SURPLUS, and DEFICIT
        audit_item = RestaurantStockAuditItem(
            audit_id=audit_record.id,
            ingredient_id=ing.id,
            ingredient_name=ing.name,
            recipe_uom=recipe_uom,
            purchase_uom=purch_uom,
            input_uom=input_uom,
            previous_stock=prev_stock,
            expected_stock=item_input.expected_stock,
            physical_count=physical_count_recipe,
            raw_input_count=raw_count,
            variance=variance,
            unit_cost_at_time=unit_cost,
            variance_rupees=variance_rupees,
            status=status_label,
            notes=item_notes
        )
        db.add(audit_item)

        # Only create ledger adjustment if there is physical variance
        if variance != Decimal("0.000"):
            items_adjusted += 1
            ledger_entry = RestaurantStockLedger(
                ingredient_id=ing.id,
                outlet_id=outlet.id,
                tenant_id=outlet.tenant_id,
                signed_quantity=variance,
                unit_cost_at_time=unit_cost,
                total_cost=abs(variance_rupees),
                reason="PHYSICAL_COUNT_ADJUSTMENT",
                source_type="stock_audit",
                source_id=batch_code,
                actor_id=manager_user.id if manager_user else None,
                notes=f"Audit {batch_code}: Counted {physical_count_recipe} {recipe_uom} vs System {prev_stock} {recipe_uom} (Variance: {variance:+} {recipe_uom})"
            )
            db.add(ledger_entry)
            ing.current_stock = physical_count_recipe
            # Guard 3: Do NOT overwrite ing.last_restocked_at!

        results.append(StockAuditItemResult(
            ingredient_id=ing.id,
            ingredient_name=ing.name,
            recipe_uom=recipe_uom,
            purchase_uom=purch_uom,
            previous_stock=prev_stock,
            expected_stock=item_input.expected_stock,
            physical_count=physical_count_recipe,
            raw_input_count=raw_count,
            variance=variance,
            variance_rupees=variance_rupees,
            status=status_label,
            notes=item_notes
        ))

    net_variance_rupees = total_surplus_rupees - total_deficit_rupees

    audit_record.items_adjusted = items_adjusted
    audit_record.total_surplus_rupees = total_surplus_rupees
    audit_record.total_deficit_rupees = total_deficit_rupees
    audit_record.net_variance_rupees = net_variance_rupees

    db.commit()

    return StockAuditBatchResponse(
        audit_batch_id=batch_code,
        audit_date=audit_date,
        audit_started_at=payload.audit_started_at,
        outlet_id=outlet.id,
        total_items_audited=len(sorted_items),
        items_adjusted=items_adjusted,
        total_surplus_rupees=total_surplus_rupees,
        total_deficit_rupees=total_deficit_rupees,
        net_variance_rupees=net_variance_rupees,
        notes=payload.notes,
        results=results
    )


@router.get("/audits", response_model=List[StockAuditBatchSummary])
def get_stock_audits(
    outlet_id: Optional[UUID] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List past physical stock audit batches with aggregate summary metrics.
    Supports search by batch # (e.g. AUDIT-2026...) or auditor name.
    """
    outlet = resolve_outlet(db, outlet_id)

    # Primary: Query dedicated RestaurantStockAudit table
    query = db.query(RestaurantStockAudit).options(
        joinedload(RestaurantStockAudit.auditor)
    ).filter(
        RestaurantStockAudit.outlet_id == outlet.id
    ).order_by(
        RestaurantStockAudit.created_at.desc()
    )

    if search:
        search_term = f"%{search.strip()}%"
        query = query.filter(RestaurantStockAudit.batch_code.ilike(search_term))

    actual_limit = limit.default if hasattr(limit, "default") else int(limit)
    actual_offset = offset.default if hasattr(offset, "default") else int(offset)
    audits = query.offset(actual_offset).limit(actual_limit).all()

    if audits:
        summaries = []
        for a in audits:
            auditor_name = "Manager / Auditor"
            if a.auditor:
                auditor_name = getattr(a.auditor, "name", None) or getattr(a.auditor, "phone", None) or "Auditor"

            summaries.append(StockAuditBatchSummary(
                audit_batch_id=a.batch_code,
                audit_date=a.audit_date,
                created_at=a.created_at,
                outlet_id=a.outlet_id,
                auditor_name=auditor_name,
                items_adjusted=a.items_adjusted,
                total_surplus_rupees=a.total_surplus_rupees or Decimal("0.00"),
                total_deficit_rupees=a.total_deficit_rupees or Decimal("0.00"),
                net_variance_rupees=a.net_variance_rupees or Decimal("0.00")
            ))
        return summaries

    # Fallback for legacy audits stored purely in RestaurantStockLedger
    ledger_query = db.query(
        RestaurantStockLedger.source_id,
        func.min(RestaurantStockLedger.created_at).label("created_at"),
        RestaurantStockLedger.actor_id,
        func.count(RestaurantStockLedger.id).label("items_adjusted")
    ).filter(
        RestaurantStockLedger.outlet_id == outlet.id,
        RestaurantStockLedger.source_type == "stock_audit"
    ).group_by(
        RestaurantStockLedger.source_id,
        RestaurantStockLedger.actor_id
    ).order_by(
        func.min(RestaurantStockLedger.created_at).desc()
    )

    if search:
        search_term = f"%{search.strip()}%"
        ledger_query = ledger_query.filter(RestaurantStockLedger.source_id.ilike(search_term))

    batches = ledger_query.offset(actual_offset).limit(actual_limit).all()

    summaries = []
    for b in batches:
        batch_id = b.source_id
        if not batch_id:
            continue

        entries = db.query(RestaurantStockLedger).filter(
            RestaurantStockLedger.outlet_id == outlet.id,
            RestaurantStockLedger.source_type == "stock_audit",
            RestaurantStockLedger.source_id == batch_id
        ).all()

        surplus = Decimal("0.00")
        deficit = Decimal("0.00")
        for e in entries:
            qty = Decimal(str(e.signed_quantity or 0))
            cost = Decimal(str(e.total_cost or 0))
            if qty > Decimal("0.000"):
                surplus += cost
            elif qty < Decimal("0.000"):
                deficit += cost

        auditor_name = "Manager / Auditor"
        if b.actor_id:
            actor = db.query(User).filter(User.id == b.actor_id).first()
            if actor:
                auditor_name = getattr(actor, "name", None) or getattr(actor, "phone", None) or "Auditor"

        summaries.append(StockAuditBatchSummary(
            audit_batch_id=batch_id,
            audit_date=b.created_at.date() if b.created_at else get_current_date(),
            created_at=b.created_at or get_current_time(),
            outlet_id=outlet.id,
            auditor_name=auditor_name,
            items_adjusted=b.items_adjusted,
            total_surplus_rupees=surplus,
            total_deficit_rupees=deficit,
            net_variance_rupees=surplus - deficit
        ))

    return summaries


@router.get("/audits/{batch_id}", response_model=StockAuditBatchResponse)
def get_stock_audit_detail(
    batch_id: str,
    outlet_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Get detailed breakdown of a specific physical stock audit batch.
    Returns 100% of counted items (including MATCHED zero-variance items).
    """
    outlet = resolve_outlet(db, outlet_id)

    # Primary: Fetch from RestaurantStockAudit
    audit = db.query(RestaurantStockAudit).options(
        joinedload(RestaurantStockAudit.items)
    ).filter(
        RestaurantStockAudit.outlet_id == outlet.id,
        RestaurantStockAudit.batch_code == batch_id
    ).first()

    if audit:
        results = [
            StockAuditItemResult(
                ingredient_id=item.ingredient_id,
                ingredient_name=item.ingredient_name or "Unknown",
                recipe_uom=item.recipe_uom,
                purchase_uom=item.purchase_uom or "",
                previous_stock=item.previous_stock,
                expected_stock=item.expected_stock,
                physical_count=item.physical_count,
                raw_input_count=item.raw_input_count,
                variance=item.variance,
                variance_rupees=item.variance_rupees,
                status=item.status,
                notes=item.notes
            )
            for item in audit.items
        ]
        return StockAuditBatchResponse(
            audit_batch_id=audit.batch_code,
            audit_date=audit.audit_date,
            audit_started_at=audit.audit_started_at,
            outlet_id=audit.outlet_id,
            total_items_audited=audit.total_items_audited,
            items_adjusted=audit.items_adjusted,
            total_surplus_rupees=audit.total_surplus_rupees,
            total_deficit_rupees=audit.total_deficit_rupees,
            net_variance_rupees=audit.net_variance_rupees,
            notes=audit.notes,
            results=results
        )

    # Fallback: Reconstruct from RestaurantStockLedger if created on older version
    entries = db.query(RestaurantStockLedger).options(
        joinedload(RestaurantStockLedger.ingredient)
    ).filter(
        RestaurantStockLedger.outlet_id == outlet.id,
        RestaurantStockLedger.source_type == "stock_audit",
        RestaurantStockLedger.source_id == batch_id
    ).all()

    if not entries:
        raise HTTPException(status_code=404, detail="Audit batch not found")

    total_surplus = Decimal("0.00")
    total_deficit = Decimal("0.00")
    audit_date = entries[0].created_at.date() if entries[0].created_at else get_current_date()
    results = []

    for e in entries:
        qty = Decimal(str(e.signed_quantity or 0))
        cost = Decimal(str(e.total_cost or 0))
        ing = e.ingredient
        ing_name = ing.name if ing else "Unknown"
        recipe_uom = (ing.recipe_uom or ing.unit or "").strip().upper() if ing else ""
        purch_uom = (ing.purchase_uom or "").strip().upper() if ing else ""

        match = re.search(r"Counted ([\d\.\-]+) .* vs System ([\d\.\-]+)", e.notes or "")
        if match:
            phys_count = Decimal(match.group(1))
            prev_stock = Decimal(match.group(2))
        else:
            phys_count = Decimal("0.000")
            prev_stock = Decimal("0.000")

        if qty > Decimal("0.000"):
            status_label = "SURPLUS"
            var_rs = cost
            total_surplus += cost
        elif qty < Decimal("0.000"):
            status_label = "DEFICIT"
            var_rs = -cost
            total_deficit += cost
        else:
            status_label = "MATCHED"
            var_rs = Decimal("0.00")

        results.append(StockAuditItemResult(
            ingredient_id=e.ingredient_id,
            ingredient_name=ing_name,
            recipe_uom=recipe_uom,
            purchase_uom=purch_uom,
            previous_stock=prev_stock,
            physical_count=phys_count,
            variance=qty,
            variance_rupees=var_rs,
            status=status_label
        ))

    return StockAuditBatchResponse(
        audit_batch_id=batch_id,
        audit_date=audit_date,
        outlet_id=outlet.id,
        total_items_audited=len(results),
        items_adjusted=len([r for r in results if r.variance != Decimal("0.000")]),
        total_surplus_rupees=total_surplus,
        total_deficit_rupees=total_deficit,
        net_variance_rupees=total_surplus - total_deficit,
        results=results
    )


# ----------------- RECIPES / BOM -----------------

def _enrich_recipe_response(recipe: RestaurantRecipe, db: Session) -> RestaurantRecipe:
    cost_data = calculate_recipe_costing_data(recipe, db)
    setattr(recipe, "item_name", cost_data.get("item_name"))
    setattr(recipe, "selling_price", cost_data.get("selling_price"))
    setattr(recipe, "plate_cost", cost_data.get("plate_cost"))
    setattr(recipe, "food_cost_percentage", cost_data.get("food_cost_percentage"))
    setattr(recipe, "gross_margin_percentage", cost_data.get("gross_margin_percentage"))
    setattr(recipe, "cost_status", cost_data.get("cost_status"))
    if recipe.item_id:
        menu_item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == recipe.item_id).first()
        if menu_item:
            category_name = None
            if hasattr(menu_item, "category") and menu_item.category:
                category_name = getattr(menu_item.category, "name", None)
            setattr(recipe, "item_category", category_name or "Menu Dish")
    for l in (recipe.lines or []):
        ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == l.ingredient_id).first()
        if ing:
            setattr(l, "ingredient_name", ing.name)
            setattr(l, "cost_per_unit", ing.cost_per_unit)
            portion_qty = (l.quantity_required / (recipe.yield_servings or Decimal("1.00")))
            setattr(l, "line_cost", (portion_qty * (ing.cost_per_unit or Decimal("0.00"))).quantize(Decimal("0.01")))
    return recipe


@router.get("/recipes", response_model=List[RecipeResponse])
def get_all_recipes(
    outlet_id: Optional[UUID] = None,
    item_id: Optional[UUID] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List all Bill of Materials (BOM) recipes with real-time plate costs, food cost %, and margins.
    """
    query = db.query(RestaurantRecipe)
    if outlet_id:
        query = query.filter((RestaurantRecipe.outlet_id == outlet_id) | (RestaurantRecipe.outlet_id == None))
    if item_id:
        query = query.filter(RestaurantRecipe.item_id == item_id)
    
    recipes = query.all()
    enriched = []
    for r in recipes:
        _enrich_recipe_response(r, db)
        if search and search.strip():
            s = search.strip().lower()
            name_match = (getattr(r, "item_name", "") or "").lower()
            cat_match = (getattr(r, "item_category", "") or "").lower()
            var_match = (r.variant_name or "").lower()
            if s not in name_match and s not in cat_match and s not in var_match:
                continue
        enriched.append(r)
    return enriched


@router.post("/recipes", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Define or update Bill of Materials (BOM) linking a menu dish, modifier add-on, or batch prep to required ingredients.
    Includes automated UOM mismatch protection (normalizes KG/LTR/etc to ingredient recipe_uom).
    """
    if not payload.item_id and not payload.modifier_option_id and not payload.produced_ingredient_id:
        raise HTTPException(
            status_code=400,
            detail="Recipe must be linked to at least one target: 'item_id', 'modifier_option_id', or 'produced_ingredient_id'."
        )

    # Check for existing recipe to update (upsert pattern)
    recipe = None
    if payload.id:
        recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.id == payload.id).first()
    elif payload.item_id:
        recipe = (
            db.query(RestaurantRecipe)
            .filter(
                RestaurantRecipe.item_id == payload.item_id,
                RestaurantRecipe.variant_name == (payload.variant_name or "Standard"),
                (RestaurantRecipe.outlet_id == payload.outlet_id) | (RestaurantRecipe.outlet_id == None)
            )
            .first()
        )

    if recipe:
        recipe.variant_name = payload.variant_name or "Standard"
        recipe.yield_servings = payload.yield_servings or Decimal("1.00")
        recipe.instructions = payload.instructions
        if payload.outlet_id:
            recipe.outlet_id = payload.outlet_id
    else:
        recipe = RestaurantRecipe(
            item_id=payload.item_id,
            modifier_option_id=payload.modifier_option_id,
            produced_ingredient_id=payload.produced_ingredient_id,
            outlet_id=payload.outlet_id,
            variant_name=payload.variant_name or "Standard",
            yield_servings=payload.yield_servings or Decimal("1.00"),
            instructions=payload.instructions
        )
        db.add(recipe)
        db.flush()

    recipe_items = []
    for line in payload.lines:
        ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == line.ingredient_id).first()
        if not ing:
            raise HTTPException(status_code=400, detail=f"Ingredient ID {line.ingredient_id} not found.")

        # UOM Mismatch Protection: Normalize to ingredient's recipe UOM
        target_uom = ing.recipe_uom or ing.unit or "G"
        norm_qty, norm_uom = normalize_recipe_uom(
            quantity=line.quantity_required,
            from_unit=line.unit,
            target_uom=target_uom,
            conversion_factor=ing.uom_conversion_factor
        )

        recipe_items.append({
            "ingredient_id": str(line.ingredient_id),
            "quantity_required": float(norm_qty),
            "unit": norm_uom
        })

    recipe.items = recipe_items
    db.commit()
    db.refresh(recipe)

    return _enrich_recipe_response(recipe, db)


@router.delete("/recipes/{recipe_id}", status_code=status.HTTP_200_OK)
def delete_recipe(
    recipe_id: UUID,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Delete a Recipe Bill of Materials (BOM).
    """
    recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    db.delete(recipe)
    db.commit()
    return {"message": "Recipe deleted successfully.", "recipe_id": str(recipe_id)}


@router.get("/recipes/{item_id}", response_model=List[RecipeResponse])
def get_item_recipes(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    recipes = (
        db.query(RestaurantRecipe)
        .filter(RestaurantRecipe.item_id == item_id)
        .all()
    )
    for r in recipes:
        for l in (r.lines or []):
            ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == l.ingredient_id).first()
            if ing:
                setattr(l, "ingredient_name", ing.name)
                setattr(l, "cost_per_unit", ing.cost_per_unit)
                portion_qty = (l.quantity_required / (r.yield_servings or Decimal("1.00")))
                setattr(l, "line_cost", (portion_qty * (ing.cost_per_unit or Decimal("0.00"))).quantize(Decimal("0.01")))
    return recipes


@router.get("/recipes/modifier/{modifier_option_id}", response_model=List[RecipeResponse])
def get_modifier_recipes(
    modifier_option_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Get recipes linked to an add-on modifier option (e.g. Extra Cheese Slice).
    """
    recipes = (
        db.query(RestaurantRecipe)
        .filter(RestaurantRecipe.modifier_option_id == modifier_option_id)
        .all()
    )
    for r in recipes:
        for l in (r.lines or []):
            ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == l.ingredient_id).first()
            if ing:
                setattr(l, "ingredient_name", ing.name)
                setattr(l, "cost_per_unit", ing.cost_per_unit)
                portion_qty = (l.quantity_required / (r.yield_servings or Decimal("1.00")))
                setattr(l, "line_cost", (portion_qty * (ing.cost_per_unit or Decimal("0.00"))).quantize(Decimal("0.01")))
    return recipes


@router.get("/recipes/{item_id}/costing", response_model=List[RecipeCostingResponse])
def get_item_recipe_costing(
    item_id: UUID,
    selling_price: Optional[Decimal] = Query(None, description="Optional selling price override to test profit margins"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Real-time Food Cost % and Plate Cost calculation using Moving Weighted Average Cost (WAC).
    Flags dishes whose food cost exceeds 30-35% threshold:
    - 'IDEAL': <= 30%
    - 'WARNING': 30% - 35%
    - 'CRITICAL_SPIKE': > 35%
    """
    recipes = (
        db.query(RestaurantRecipe)
        .filter(RestaurantRecipe.item_id == item_id)
        .all()
    )
    if not recipes:
        raise HTTPException(status_code=404, detail="No recipe found for this menu item.")

    costing_list = []
    for r in recipes:
        cost_data = calculate_recipe_costing_data(r, db, selling_price_override=selling_price)
        costing_list.append(RecipeCostingResponse(**cost_data))

    return costing_list


# ----------------- STOCK CONSUMPTION STREAM -----------------

@router.get("/consumption")
def get_stock_consumption_stream(
    outlet_id: Optional[UUID] = Query(None, description="Branch outlet ID (auto-resolves to active branch if omitted)"),
    reason: Optional[str] = None, # ORDER_CONSUMPTION, REVERSAL, WASTAGE
    search: Optional[str] = None,
    limit: int = 150,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Live stream of automatic stock deductions triggered by POS KOT dispatches, voids, and wastage.
    Includes Moving Weighted Average Cost (WAC) valuation snapshots.
    Strictly isolated per outlet_id and tenant_id.
    """
    target_outlet = resolve_outlet(db, outlet_id)
    query = (
        db.query(RestaurantStockLedger)
        .options(joinedload(RestaurantStockLedger.ingredient))
    )
    if outlet_id:
        has_specific = query.filter(RestaurantStockLedger.outlet_id == outlet_id).first()
        if has_specific:
            query = query.filter(RestaurantStockLedger.outlet_id == outlet_id)
        elif target_outlet:
            has_target = query.filter(RestaurantStockLedger.outlet_id == target_outlet.id).first()
            if has_target:
                query = query.filter((RestaurantStockLedger.outlet_id == target_outlet.id) | (RestaurantStockLedger.outlet_id == None))
    elif target_outlet:
        has_records = query.filter(RestaurantStockLedger.outlet_id == target_outlet.id).first()
        if has_records:
            query = query.filter((RestaurantStockLedger.outlet_id == target_outlet.id) | (RestaurantStockLedger.outlet_id == None))
    
    if reason and reason.strip():
        query = query.filter(RestaurantStockLedger.reason == reason.strip().upper())
    else:
        query = query.filter(
            or_(
                RestaurantStockLedger.reason.in_(["ORDER_CONSUMPTION", "REVERSAL", "WASTAGE", "CONSUMPTION", "KOT_DISPATCH", "ORDER"]),
                RestaurantStockLedger.source_type.in_(["order", "order_void", "order_waste"])
            )
        )

    records = (
        query.order_by(RestaurantStockLedger.created_at.desc())
        .limit(limit)
        .all()
    )

    # Cache orders for fast lookup
    order_ids = {r.source_id for r in records if r.source_id and r.source_type == "order"}
    orders_map = {}
    if order_ids:
        valid_uuids = []
        for oid in order_ids:
            try:
                valid_uuids.append(UUID(oid))
            except (ValueError, TypeError):
                pass
        if valid_uuids:
            orders = db.query(RestaurantOrder).filter(RestaurantOrder.id.in_(valid_uuids)).all()
            for o in orders:
                orders_map[str(o.id)] = o

    raw_items = []
    total_consumption_inr = Decimal("0.00")
    total_reversal_inr = Decimal("0.00")
    total_wastage_inr = Decimal("0.00")

    for r in records:
        cost_val = Decimal(str(r.total_cost or 0.00))
        if cost_val == Decimal("0.00") and r.unit_cost_at_time and r.signed_quantity:
            cost_val = Decimal(str(round(abs(float(r.signed_quantity)) * float(r.unit_cost_at_time), 2)))

        if r.reason in ("ORDER_CONSUMPTION", "CONSUMPTION", "KOT_DISPATCH", "ORDER"):
            total_consumption_inr += cost_val
        elif r.reason == "REVERSAL":
            total_reversal_inr += cost_val
        elif r.reason == "WASTAGE":
            total_wastage_inr += cost_val
        elif r.signed_quantity and r.signed_quantity < 0:
            total_consumption_inr += cost_val

        order_obj = orders_map.get(str(r.source_id)) if r.source_id else None
        order_num = order_obj.order_number if order_obj else (f"ORD-{str(r.source_id)[:6]}" if r.source_id else "KOT-ORDER")

        # Parse dish name and portions from notes if available
        # notes format: "KOT consumption for 2x Chicken Biryani (Standard)"
        dish_name = "Dish Consumption"
        portions = 1
        if r.notes:
            m = re.search(r"for\s+(\d+)x\s+([^:]+)", r.notes)
            if m:
                portions = int(m.group(1))
                dish_name = m.group(2).strip()
            else:
                dish_name = r.notes

        ing_name = r.ingredient.name if r.ingredient else "Ingredient"
        uom = r.ingredient.recipe_uom or r.ingredient.unit or "G" if r.ingredient else "G"
        qty_consumed = abs(float(r.signed_quantity))

        item_data = {
            "id": str(r.id),
            "order_id": str(r.source_id or ""),
            "order_number": order_num,
            "dish_name": dish_name,
            "portions": portions,
            "ingredient_id": str(r.ingredient_id),
            "ingredient_name": ing_name,
            "quantity_consumed": qty_consumed,
            "signed_quantity": float(r.signed_quantity),
            "unit": uom,
            "unit_cost": float(r.unit_cost_at_time or 0.0),
            "total_cost": float(r.total_cost or 0.0),
            "reason": r.reason,
            "notes": r.notes or "",
            "timestamp": r.created_at.isoformat()
        }

        if search and search.strip():
            s = search.strip().lower()
            if (s not in dish_name.lower() and
                s not in order_num.lower() and
                s not in ing_name.lower() and
                s not in (r.source_id or "").lower()):
                continue

        raw_items.append(item_data)

    # Group into order-level deduction events
    grouped_events = {}
    for it in raw_items:
        key = f"{it['order_id']}_{it['dish_name']}_{it['timestamp'][:16]}"
        if key not in grouped_events:
            grouped_events[key] = {
                "id": it["id"],
                "order_id": it["order_number"],
                "raw_order_id": it["order_id"],
                "dish_name": it["dish_name"],
                "portions_prepared": it["portions"],
                "timestamp": it["timestamp"],
                "reason": it["reason"],
                "total_batch_cost": 0.0,
                "deductions": []
            }
        g = grouped_events[key]
        g["total_batch_cost"] += it["total_cost"]
        deduction_str = f"{it['ingredient_name']} ({it['quantity_consumed']:.1f} {it['unit']} - ₹{it['total_cost']:.2f})"
        g["deductions"].append(deduction_str)

    events_list = list(grouped_events.values())

    return {
        "status": "ACTIVE",
        "outlet_id": str(target_outlet.id),
        "outlet_name": target_outlet.name,
        "total_records": len(raw_items),
        "summary": {
            "total_consumption_inr": float(total_consumption_inr),
            "total_reversals_inr": float(total_reversal_inr),
            "total_wastage_inr": float(total_wastage_inr),
        },
        "events": events_list,
        "ledger_stream": raw_items
    }


# ----------------- WASTAGE & SPOILAGE TRACKING -----------------

@router.get("/waste")
def get_wastage_logs(
    outlet_id: Optional[UUID] = Query(None, description="Branch outlet ID"),
    limit: int = Query(150, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List chronological food wastage and spoilage incidents.
    Includes raw material waste, batch prep discards, and customer returned voids.
    """
    query = (
        db.query(RestaurantStockLedger)
        .options(joinedload(RestaurantStockLedger.ingredient), joinedload(RestaurantStockLedger.actor))
        .filter(RestaurantStockLedger.reason == "WASTAGE")
    )
    if outlet_id:
        query = query.filter(RestaurantStockLedger.outlet_id == outlet_id)

    actual_limit = limit.default if hasattr(limit, "default") else int(limit)
    records = query.order_by(RestaurantStockLedger.created_at.desc()).limit(actual_limit).all()
    results = []
    for r in records:
        reason_tag = "SPOILAGE"
        if r.notes and "[" in r.notes and "]" in r.notes:
            reason_tag = r.notes.split("[")[1].split("]")[0].strip().upper()

        results.append({
            "id": str(r.id),
            "ingredient_id": str(r.ingredient_id),
            "ingredient_name": r.ingredient.name if r.ingredient else "Unknown Ingredient",
            "quantity": abs(float(r.signed_quantity)),
            "unit": r.ingredient.recipe_uom or r.ingredient.unit or "G" if r.ingredient else "G",
            "unit_cost": float(r.unit_cost_at_time or 0.0),
            "cost": float(r.total_cost or 0.0),
            "waste_reason": reason_tag,
            "source_type": r.source_type or "waste_log",
            "source_id": r.source_id or "",
            "notes": r.notes or "",
            "reported_by": r.actor.name if r.actor else "Staff",
            "reported_at": r.created_at.isoformat()
        })
    return results


@router.post("/waste", response_model=StockLedgerResponse, status_code=status.HTTP_201_CREATED)
def record_ingredient_waste(
    payload: WasteLogCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Log raw material wastage or spoilage (e.g. sour milk, rotten produce, prep trim, dropped ingredient).
    - Automatically normalizes UOM (e.g. 2.5 KG chicken -> 2500 G).
    - Deducts stock balance atomically using SELECT ... FOR UPDATE.
    - Snapshots live Moving Weighted Average Cost (WAC) to record exact financial loss in Rupees.
    - Append-only stock ledger entry with reason = 'WASTAGE'.
    """
    ingredient = (
        db.query(RestaurantIngredient)
        .filter(RestaurantIngredient.id == payload.ingredient_id)
        .with_for_update()
        .first()
    )
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    target_uom = ingredient.recipe_uom or ingredient.unit or "G"
    norm_qty, norm_uom = normalize_recipe_uom(
        quantity=payload.quantity,
        from_unit=payload.input_uom,
        target_uom=target_uom,
        conversion_factor=ingredient.uom_conversion_factor
    )

    unit_cost = ingredient.cost_per_unit or Decimal("0.0000")
    total_cost_val = (norm_qty * unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    waste_code = f"WST-{get_current_time().strftime('%Y%m%d%H%M%S')}"
    waste_reason_tag = (payload.waste_reason or "SPOILAGE").strip().upper()
    notes_str = f"[{waste_reason_tag}] {payload.notes or 'Material loss/spoilage'} (Logged: {payload.quantity} {payload.input_uom or target_uom})"

    ledger_entry = RestaurantStockLedger(
        ingredient_id=ingredient.id,
        outlet_id=ingredient.outlet_id,
        tenant_id=ingredient.tenant_id,
        signed_quantity=-norm_qty, # Negative deduction
        unit_cost_at_time=unit_cost,
        total_cost=total_cost_val,
        reason="WASTAGE",
        source_type="waste_log",
        source_id=waste_code,
        actor_id=current_user.id if current_user else None,
        notes=notes_str
    )
    db.add(ledger_entry)

    # Deduct current stock
    ingredient.current_stock -= norm_qty
    db.commit()
    db.refresh(ledger_entry)
    return ledger_entry


@router.post("/waste/dish", status_code=status.HTTP_201_CREATED)
def record_dish_waste(
    payload: DishWasteLogCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Log wastage of prepared/cooked dishes for UNBILLED kitchen losses (e.g. burnt pot of gravy during prep,
    buffet tray expired, dropped unpunched food, staff tasting).
    
    OPERATIONAL BOUNDARY:
    - Cooked Dish Waste (this endpoint) = UNBILLED losses. Deducts constituent ingredients via Recipe BOM.
    - POS Order Void (POST .../items/{id}/void with is_waste = True) = BILLED customer orders already sent
      to kitchen (stock was already deducted at KOT; logs WASTAGE with signed_quantity = 0.000 to prevent double-deduction).
    """
    menu_item = db.query(RestaurantMenuItem).filter(RestaurantMenuItem.id == payload.item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    target_outlet = resolve_outlet(db, payload.outlet_id or menu_item.outlet_id)
    outlet_id = target_outlet.id

    # Find recipe
    recipe = (
        db.query(RestaurantRecipe)
        .filter(RestaurantRecipe.item_id == payload.item_id, RestaurantRecipe.variant_name == payload.variant_name)
        .first()
    )
    if not recipe:
        recipe = db.query(RestaurantRecipe).filter(RestaurantRecipe.item_id == payload.item_id).first()

    if not recipe or not recipe.lines:
        raise HTTPException(status_code=400, detail="No recipe (BOM) found for this dish to calculate ingredient waste.")

    yield_val = Decimal(str(recipe.yield_servings or 1.00))
    if yield_val <= Decimal("0.00"):
        yield_val = Decimal("1.00")

    portions = Decimal(str(payload.portions or 1.00))
    waste_code = f"DISH-WST-{get_current_time().strftime('%Y%m%d%H%M%S')}"
    waste_reason_tag = (payload.waste_reason or "BURNT_RUINED").strip().upper()

    # Multi-Branch Resolution: resolve each ingredient for this branch's local warehouse
    target_ing_map = {}
    for r_line in recipe.lines:
        base_ing = db.query(RestaurantIngredient).filter(RestaurantIngredient.id == r_line.ingredient_id).first()
        if base_ing:
            resolved_ing = resolve_branch_ingredient(db, base_ing, outlet_id)
            target_ing_map[r_line.id] = (r_line, resolved_ing)

    # Deadlock-free row locking: lock rows in strictly ascending UUID order
    unique_ing_ids = sorted(list({ing.id for _, ing in target_ing_map.values()}), key=lambda x: str(x))
    if unique_ing_ids:
        db.query(RestaurantIngredient)\
            .filter(RestaurantIngredient.id.in_(unique_ing_ids))\
            .order_by(RestaurantIngredient.id)\
            .with_for_update()\
            .all()

    total_loss_inr = Decimal("0.00")
    deductions = []

    for r_line, ing in target_ing_map.values():
        norm_qty, norm_uom = normalize_recipe_uom(
            r_line.quantity_required,
            r_line.unit,
            ing.recipe_uom,
            ing.uom_conversion_factor
        )
        consumed_qty = (norm_qty / yield_val) * portions
        unit_cost = ing.cost_per_unit or Decimal("0.0000")
        line_cost = (consumed_qty * unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_loss_inr += line_cost

        ing.current_stock -= consumed_qty

        ledger = RestaurantStockLedger(
            ingredient_id=ing.id,
            outlet_id=outlet_id,
            tenant_id=ing.tenant_id,
            signed_quantity=-consumed_qty,
            unit_cost_at_time=unit_cost,
            total_cost=line_cost,
            reason="WASTAGE",
            source_type="dish_waste",
            source_id=waste_code,
            actor_id=current_user.id if current_user else None,
            notes=f"[{waste_reason_tag}] Wasted {portions}x {menu_item.name} ({payload.variant_name}): {payload.notes or ''} [Qty: {consumed_qty} {norm_uom}]"
        )
        db.add(ledger)
        deductions.append({
            "ingredient_name": ing.name,
            "quantity_wasted": float(consumed_qty),
            "unit": norm_uom,
            "loss_inr": float(line_cost)
        })

    db.commit()

    return {
        "status": "LOGGED",
        "outlet_id": str(outlet_id),
        "outlet_name": target_outlet.name,
        "waste_code": waste_code,
        "dish_name": menu_item.name,
        "variant_name": payload.variant_name,
        "portions_wasted": float(portions),
        "waste_reason": waste_reason_tag,
        "total_financial_loss_inr": float(total_loss_inr),
        "ingredient_deductions": deductions
    }


@router.get("/waste/summary")
def get_wastage_summary(
    outlet_id: Optional[UUID] = Query(None, description="Branch outlet ID (auto-resolves to active branch if omitted)"),
    days: int = Query(30, ge=1, le=365, description="Number of past days to analyze"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Analytics summary of food spoilage, preparation losses, and customer returns.
    Strictly scoped per outlet_id and tenant_id to prevent multi-branch data blending.
    - Correctly calculates losses for both raw waste (-signed_qty) and POS void waste (signed_qty = 0.000).
    - Breakdown by waste reason (Spoilage, Burning, Expiry, Customer Returns).
    - Top wasted ingredients by financial loss and quantity.
    """
    from datetime import timedelta
    start_date = get_current_time() - timedelta(days=days)
    target_outlet = resolve_outlet(db, outlet_id)

    query = (
        db.query(RestaurantStockLedger)
        .options(joinedload(RestaurantStockLedger.ingredient))
        .filter(RestaurantStockLedger.outlet_id == target_outlet.id)
        .filter(RestaurantStockLedger.reason == "WASTAGE")
        .filter(RestaurantStockLedger.created_at >= start_date)
    )
    if current_user and getattr(current_user, "tenant_id", None):
        query = query.filter(RestaurantStockLedger.tenant_id == current_user.tenant_id)

    records = query.all()

    total_loss_inr = Decimal("0.00")
    by_reason = {}
    by_ingredient = {}

    for r in records:
        cost = Decimal(str(r.total_cost or 0.00))
        total_loss_inr += cost

        # Extract waste category from notes [TAG]
        reason_tag = "SPOILAGE"
        if r.notes and "[" in r.notes and "]" in r.notes:
            reason_tag = r.notes.split("[")[1].split("]")[0].strip().upper()
        by_reason[reason_tag] = by_reason.get(reason_tag, Decimal("0.00")) + cost

        # Group by ingredient
        ing_id = str(r.ingredient_id)
        ing_name = r.ingredient.name if r.ingredient else "Unknown Ingredient"
        uom = r.ingredient.recipe_uom or r.ingredient.unit or "G" if r.ingredient else "G"
        
        # Safe quantity extraction: if signed_quantity == 0 (order_waste POS void), parse from notes [Qty: ...] or cost / unit_cost
        qty = abs(Decimal(str(r.signed_quantity)))
        if qty == Decimal("0.000"):
            if r.notes and "[Qty:" in r.notes:
                try:
                    raw_q = r.notes.split("[Qty:")[1].split("]")[0].strip().split()[0]
                    qty = Decimal(raw_q)
                except Exception:
                    if r.unit_cost_at_time and r.unit_cost_at_time > 0:
                        qty = (cost / r.unit_cost_at_time).quantize(Decimal("0.001"))
            elif r.unit_cost_at_time and r.unit_cost_at_time > 0:
                qty = (cost / r.unit_cost_at_time).quantize(Decimal("0.001"))

        if ing_id not in by_ingredient:
            by_ingredient[ing_id] = {
                "ingredient_id": ing_id,
                "ingredient_name": ing_name,
                "unit": uom,
                "total_quantity_wasted": Decimal("0.00"),
                "total_loss_inr": Decimal("0.00"),
                "incidents_count": 0
            }
        by_ingredient[ing_id]["total_quantity_wasted"] += qty
        by_ingredient[ing_id]["total_loss_inr"] += cost
        by_ingredient[ing_id]["incidents_count"] += 1

    # Sort top wasted ingredients by financial loss descending
    sorted_ingredients = sorted(
        by_ingredient.values(),
        key=lambda x: x["total_loss_inr"],
        reverse=True
    )

    formatted_ingredients = [
        {
            "ingredient_id": item["ingredient_id"],
            "ingredient_name": item["ingredient_name"],
            "unit": item["unit"],
            "total_quantity_wasted": float(item["total_quantity_wasted"]),
            "total_loss_inr": float(item["total_loss_inr"].quantize(Decimal("0.01"))),
            "incidents_count": item["incidents_count"]
        }
        for item in sorted_ingredients[:20] # Top 20
    ]

    formatted_reasons = {
        k: float(v.quantize(Decimal("0.01")))
        for k, v in sorted(by_reason.items(), key=lambda item: item[1], reverse=True)
    }

    return {
        "status": "ACTIVE",
        "outlet_id": str(target_outlet.id),
        "outlet_name": target_outlet.name,
        "timeframe_days": days,
        "total_waste_incidents": len(records),
        "total_financial_loss_inr": float(total_loss_inr.quantize(Decimal("0.01"))),
        "loss_by_reason_inr": formatted_reasons,
        "top_wasted_ingredients": formatted_ingredients
    }


# ----------------- INVENTORY REPORTS & FOOD COST RECONCILIATION -----------------

@router.get("/reports/reconciliation")
def get_food_cost_reconciliation(
    outlet_id: Optional[UUID] = Query(None, description="Branch outlet ID"),
    days: int = Query(30, ge=1, le=365, description="Number of past days to analyze"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Actual vs. Theoretical Food Cost Reconciliation (AvT) Report.
    - Theoretical Food Cost: Recipe BOM order deductions from POS sales.
    - Actual Food Cost (COGS): Theoretical Consumption + Recorded Kitchen Wastage + Physical Count Discrepancies.
    - Variance: Unrecorded prep loss, kitchen leakage, over-portioning, or shrinkage.
    - Provides ingredient-level drill-down with health status.
    """
    from datetime import timedelta
    start_date = get_current_time() - timedelta(days=days)
    target_outlet = resolve_outlet(db, outlet_id)

    # 1. Total POS Sales Revenue
    order_query = db.query(RestaurantOrder).filter(
        RestaurantOrder.created_at >= start_date,
        RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "COMPLETED"])
    )
    if outlet_id:
        order_query = order_query.filter(RestaurantOrder.outlet_id == outlet_id)
    elif target_outlet:
        order_query = order_query.filter(RestaurantOrder.outlet_id == target_outlet.id)

    orders = order_query.all()
    total_sales_inr = sum([Decimal(str(o.grand_total or 0.00)) for o in orders], Decimal("0.00"))

    # 2. Stock Ledger movements
    ledger_query = (
        db.query(RestaurantStockLedger)
        .options(joinedload(RestaurantStockLedger.ingredient))
        .filter(RestaurantStockLedger.created_at >= start_date)
    )
    if outlet_id:
        ledger_query = ledger_query.filter((RestaurantStockLedger.outlet_id == outlet_id) | (RestaurantStockLedger.outlet_id == None))
    elif target_outlet:
        ledger_query = ledger_query.filter((RestaurantStockLedger.outlet_id == target_outlet.id) | (RestaurantStockLedger.outlet_id == None))

    records = ledger_query.all()

    # Per-ingredient aggregation
    items_map = {}
    total_theo_inr = Decimal("0.00")
    total_waste_inr = Decimal("0.00")
    total_audit_shrinkage_inr = Decimal("0.00")

    for r in records:
        ing = r.ingredient
        ing_id = str(r.ingredient_id)
        if ing_id not in items_map:
            ing_name = ing.name if ing else "Raw Ingredient"
            recipe_uom = (ing.recipe_uom or ing.unit or "G").strip().upper() if ing else "G"
            unit_cost = Decimal(str(ing.cost_per_unit or 0.0000)) if ing else Decimal("0.0000")
            cat_name = "Pantry"
            if ing and hasattr(ing, "category") and ing.category:
                cat_name = ing.category.name or "Pantry"
            items_map[ing_id] = {
                "ingredient_id": ing_id,
                "ingredient_name": ing_name,
                "category": cat_name,
                "recipe_uom": recipe_uom,
                "unit_cost": float(unit_cost),
                "theoretical_qty": Decimal("0.000"),
                "theoretical_cost": Decimal("0.00"),
                "waste_qty": Decimal("0.000"),
                "waste_cost": Decimal("0.00"),
                "audit_variance_qty": Decimal("0.000"),
                "audit_variance_cost": Decimal("0.00"),
            }

        data = items_map[ing_id]
        qty = abs(Decimal(str(r.signed_quantity or 0.000)))
        cost = Decimal(str(r.total_cost or 0.00))
        if cost == Decimal("0.00") and r.unit_cost_at_time and r.signed_quantity:
            cost = (qty * Decimal(str(r.unit_cost_at_time))).quantize(Decimal("0.01"))

        if r.reason in ("ORDER_CONSUMPTION", "CONSUMPTION", "KOT_DISPATCH") or r.source_type == "order":
            data["theoretical_qty"] += qty
            data["theoretical_cost"] += cost
            total_theo_inr += cost
        elif r.reason == "WASTAGE" or r.source_type in ("waste_log", "dish_waste", "order_waste"):
            data["waste_qty"] += qty
            data["waste_cost"] += cost
            total_waste_inr += cost
        elif r.reason == "PHYSICAL_COUNT_ADJUSTMENT" or r.source_type == "stock_audit":
            if r.signed_quantity and r.signed_quantity < Decimal("0.000"):
                data["audit_variance_qty"] -= qty
                data["audit_variance_cost"] += cost
                total_audit_shrinkage_inr += cost
            elif r.signed_quantity and r.signed_quantity > Decimal("0.000"):
                data["audit_variance_qty"] += qty

    # Calculate actual cost and health status per commodity
    breakdown_list = []
    for item in items_map.values():
        theo_cost = item["theoretical_cost"]
        waste_cost = item["waste_cost"]
        audit_loss = item["audit_variance_cost"]
        actual_cost = theo_cost + waste_cost + audit_loss
        variance_loss = waste_cost + audit_loss

        # Status determination
        if variance_loss == Decimal("0.00"):
            status_label = "BALANCED"
        elif theo_cost > 0 and (variance_loss / theo_cost) <= Decimal("0.05"):
            status_label = "CONTROLLED"
        else:
            status_label = "LEAKAGE_ALERT"

        breakdown_list.append({
            "ingredient_id": item["ingredient_id"],
            "ingredient_name": item["ingredient_name"],
            "category": item["category"],
            "recipe_uom": item["recipe_uom"],
            "unit_cost": item["unit_cost"],
            "theoretical_qty": float(item["theoretical_qty"]),
            "theoretical_cost": float(theo_cost.quantize(Decimal("0.01"))),
            "waste_qty": float(item["waste_qty"]),
            "waste_cost": float(waste_cost.quantize(Decimal("0.01"))),
            "audit_variance_qty": float(item["audit_variance_qty"]),
            "audit_variance_cost": float(audit_loss.quantize(Decimal("0.01"))),
            "actual_depletion_cost": float(actual_cost.quantize(Decimal("0.01"))),
            "variance_loss_inr": float(variance_loss.quantize(Decimal("0.01"))),
            "health_status": status_label
        })

    # Sort breakdown by variance loss descending
    breakdown_list.sort(key=lambda x: x["variance_loss_inr"], reverse=True)

    actual_cogs_inr = total_theo_inr + total_waste_inr + total_audit_shrinkage_inr
    theo_cost_pct = float((total_theo_inr / total_sales_inr * Decimal("100.00")).quantize(Decimal("0.1"))) if total_sales_inr > 0 else 0.0
    actual_cost_pct = float((actual_cogs_inr / total_sales_inr * Decimal("100.00")).quantize(Decimal("0.1"))) if total_sales_inr > 0 else 0.0
    variance_pct = round(actual_cost_pct - theo_cost_pct, 1)
    variance_inr = float((actual_cogs_inr - total_theo_inr).quantize(Decimal("0.01")))

    return {
        "status": "ACTIVE",
        "outlet_id": str(target_outlet.id),
        "outlet_name": target_outlet.name,
        "timeframe_days": days,
        "summary": {
            "total_sales_inr": float(total_sales_inr.quantize(Decimal("0.01"))),
            "theoretical_cost_inr": float(total_theo_inr.quantize(Decimal("0.01"))),
            "theoretical_cost_pct": theo_cost_pct,
            "recorded_waste_inr": float(total_waste_inr.quantize(Decimal("0.01"))),
            "audit_shrinkage_inr": float(total_audit_shrinkage_inr.quantize(Decimal("0.01"))),
            "actual_cogs_inr": float(actual_cogs_inr.quantize(Decimal("0.01"))),
            "actual_cost_pct": actual_cost_pct,
            "variance_loss_inr": variance_inr,
            "variance_pct": variance_pct,
            "target_benchmark_pct": 30.0,
        },
        "breakdown": breakdown_list
    }


@router.get("/reports/export/valuation")
def export_valuation_csv(
    outlet_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Export current warehouse stock valuation snapshot to standard CSV.
    """
    import csv
    import io
    target_outlet = resolve_outlet(db, outlet_id)
    query = (
        db.query(RestaurantIngredient)
        .options(joinedload(RestaurantIngredient.category))
        .filter(RestaurantIngredient.is_active == True)
    )
    if outlet_id:
        query = query.filter((RestaurantIngredient.outlet_id == outlet_id) | (RestaurantIngredient.outlet_id == None))
    elif target_outlet:
        query = query.filter((RestaurantIngredient.outlet_id == target_outlet.id) | (RestaurantIngredient.outlet_id == None))

    ingredients = query.order_by(RestaurantIngredient.name).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Commodity Code",
        "Ingredient Name",
        "Category / Storage Zone",
        "Current Stock",
        "Recipe Unit",
        "Cost Per Unit (INR)",
        "Total Stock Valuation (INR)",
        "ABC Tier"
    ])

    for ing in ingredients:
        curr_stock = float(ing.current_stock or 0.000)
        cost_unit = float(ing.cost_per_unit or 0.0000)
        tot_val = round(curr_stock * cost_unit, 2)
        abc_tier = "Class A (High Value)" if tot_val >= 1000 else ("Class B (Moderate)" if tot_val >= 200 else "Class C (Bulk)")
        cat_name = ing.category.name if ing.category else (ing.storage_zone or "Ambient")
        code = getattr(ing, "sku", None) or f"ING-{str(ing.id)[:6].upper()}"

        writer.writerow([
            code,
            ing.name,
            cat_name,
            f"{curr_stock:.3f}",
            ing.recipe_uom or ing.unit or "G",
            f"{cost_unit:.4f}",
            f"{tot_val:.2f}",
            abc_tier
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=stock_valuation_{get_current_time().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


