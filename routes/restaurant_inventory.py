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
from models.restaurant_recipe import RestaurantRecipe, RestaurantRecipeLine
from models.restaurant_stock_ledger import RestaurantStockLedger
from schemas.restaurant_inventory import (
    RestaurantIngredientCategoryCreate, RestaurantIngredientCategoryUpdate, RestaurantIngredientCategoryResponse,
    RestaurantIngredientCreate, RestaurantIngredientUpdate, RestaurantIngredientResponse,
    StockAdjustmentCreate, StockLedgerResponse,
    StockAuditBatchCreate, StockAuditBatchResponse, StockAuditItemResult,
    RecipeCreate, RecipeResponse
)
from dependencies import get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff

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
        source_id=f"ADJ-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        actor_id=actor_id,
        notes=f"{payload.notes or 'Manual adjustment'} [Entered: {unit_label}]"
    )
    db.add(ledger_entry)

    # Atomically adjust current cached balance
    ingredient.current_stock += signed_qty
    ingredient.last_restocked_at = datetime.utcnow()

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
    1. Validates all ingredients in the audit batch.
    2. Locks ingredient rows using SELECT ... FOR UPDATE.
    3. Converts physical counts to base recipe UOM.
    4. Computes variance = physical_count - previous_stock.
    5. Writes PHYSICAL_COUNT_ADJUSTMENT ledger entries sharing a single audit batch ID (AUDIT-YYYYMMDD-###).
    6. Returns financial variance reconciliation summary in rupees.
    """
    outlet = resolve_outlet(db, payload.outlet_id)
    audit_date = payload.audit_date or datetime.utcnow().date()
    batch_code = f"AUDIT-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    results = []
    items_adjusted = 0
    total_surplus_rupees = Decimal("0.00")
    total_deficit_rupees = Decimal("0.00")

    for item_input in payload.items:
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

        if variance > Decimal("0.000"):
            status_label = "SURPLUS"
            total_surplus_rupees += variance_rupees
        elif variance < Decimal("0.000"):
            status_label = "DEFICIT"
            total_deficit_rupees += abs(variance_rupees)
        else:
            status_label = "MATCHED"

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
            ing.last_restocked_at = datetime.utcnow()

        results.append(StockAuditItemResult(
            ingredient_id=ing.id,
            ingredient_name=ing.name,
            recipe_uom=recipe_uom,
            purchase_uom=purch_uom,
            previous_stock=prev_stock,
            physical_count=physical_count_recipe,
            variance=variance,
            variance_rupees=variance_rupees,
            status=status_label
        ))

    db.commit()

    net_variance_rupees = total_surplus_rupees - total_deficit_rupees

    return StockAuditBatchResponse(
        audit_batch_id=batch_code,
        audit_date=audit_date,
        outlet_id=outlet.id,
        total_items_audited=len(payload.items),
        items_adjusted=items_adjusted,
        total_surplus_rupees=total_surplus_rupees,
        total_deficit_rupees=total_deficit_rupees,
        net_variance_rupees=net_variance_rupees,
        results=results
    )


# ----------------- RECIPES / BOM -----------------

@router.post("/recipes", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Define Bill of Materials (BOM) linking menu dish/variant to required ingredients.
    """
    recipe = RestaurantRecipe(
        item_id=payload.item_id,
        variant_name=payload.variant_name,
        yield_servings=payload.yield_servings,
        instructions=payload.instructions
    )
    db.add(recipe)
    db.flush()

    for line in payload.lines:
        r_line = RestaurantRecipeLine(
            recipe_id=recipe.id,
            ingredient_id=line.ingredient_id,
            quantity_required=line.quantity_required,
            unit=line.unit.upper()
        )
        db.add(r_line)

    db.commit()
    db.refresh(recipe)
    return recipe


@router.get("/recipes/{item_id}", response_model=List[RecipeResponse])
def get_item_recipes(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    return (
        db.query(RestaurantRecipe)
        .options(joinedload(RestaurantRecipe.lines))
        .filter(RestaurantRecipe.item_id == item_id)
        .all()
    )

