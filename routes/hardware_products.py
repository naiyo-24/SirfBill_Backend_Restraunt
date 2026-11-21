import uuid
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from models.database import get_db
from models.user import User
from models.hardware_product import HardwareProduct, HardwareOrder
from schemas.hardware_product import (
    HardwareProductCreate,
    HardwareProductUpdate,
    HardwareProductResponse,
    HardwareCategorySummary,
    HardwareOrderCreate,
    HardwareOrderUpdate,
    HardwareOrderResponse
)
from dependencies import get_current_user, get_restaurant_staff, get_restaurant_manager

router = APIRouter(
    prefix="/api/hardware",
    tags=["Restaurant - Buy Hardware & POS Devices"]
)

# ----------------- Category Metadata -----------------
CATEGORY_METADATA = {
    "PRINTER": {
        "title": "Thermal Receipt & KOT Printers",
        "icon": "print",
        "description": "High-speed 80mm & 58mm thermal printers with USB, LAN, and Bluetooth interfaces."
    },
    "POS_TERMINAL": {
        "title": "All-in-One Touch POS Terminals",
        "icon": "desktop_windows",
        "description": "Heavy-duty dual-screen and single-screen touch billing terminals for busy billing counters."
    },
    "HANDHELD_PDA": {
        "title": "Captain Handheld Ordering Devices",
        "icon": "smartphone",
        "description": "Android mobile ordering tablets with built-in thermal printer for table-side KOT generation."
    },
    "KDS_DISPLAY": {
        "title": "Kitchen Display System (KDS) Screens",
        "icon": "tv",
        "description": "Durable commercial display screens for kitchen cooking status and station routing."
    },
    "CASH_DRAWER": {
        "title": "Electronic Cash Drawers",
        "icon": "inbox",
        "description": "Heavy-duty steel cash drawers with RJ11 auto-trigger connection to thermal printers."
    },
    "SCANNER": {
        "title": "1D / 2D Barcode & QR Scanners",
        "icon": "qr_code_scanner",
        "description": "Fast wireless and USB barcode readers for packaged items and member card lookup."
    },
    "PAPER_ROLLS": {
        "title": "Thermal Paper Rolls & Consumables",
        "icon": "receipt_long",
        "description": "BPA-free high-density thermal paper rolls (80mm & 58mm) for crisp, long-lasting printouts."
    },
    "ACCESSORY": {
        "title": "Cables, Hubs & Mounts",
        "icon": "settings_input_hdmi",
        "description": "Industrial network switches, USB extensions, cash drawer trigger cables, and wall brackets."
    }
}


# ============================================================================
# Product Catalog Endpoints
# ============================================================================
@router.get("/categories", response_model=List[HardwareCategorySummary])
def get_hardware_categories(db: Session = Depends(get_db)):
    """
    List all hardware categories with product counts and UI metadata.
    Includes 'ALL' as the first category for unified catalog views.
    """
    counts = (
        db.query(HardwareProduct.category, func.count(HardwareProduct.id))
        .filter(HardwareProduct.is_active == True)
        .group_by(HardwareProduct.category)
        .all()
    )
    count_map = {row[0].upper(): row[1] for row in counts}
    total_count = sum(count_map.values())

    results = [
        HardwareCategorySummary(
            category="ALL",
            title="All Hardware",
            count=total_count,
            icon="storefront",
            description="Browse complete catalog of all certified POS terminals, printers, KDS, handhelds, and accessories."
        )
    ]
    for cat_code, meta in CATEGORY_METADATA.items():
        results.append(
            HardwareCategorySummary(
                category=cat_code,
                title=meta["title"],
                count=count_map.get(cat_code, 0),
                icon=meta["icon"],
                description=meta["description"]
            )
        )
    return results


@router.get("/products", response_model=List[HardwareProductResponse])
def get_hardware_products(
    category: Optional[str] = None,
    brand: Optional[str] = None,
    in_stock_only: bool = False,
    featured_only: bool = False,
    popular_only: bool = False,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Browse hardware catalog with filtering by category, search query, and stock flags.
    """
    query = db.query(HardwareProduct).filter(HardwareProduct.is_active == True)

    if category and category.strip().upper() != "ALL":
        query = query.filter(HardwareProduct.category == category.strip().upper())
    if brand:
        query = query.filter(HardwareProduct.brand.ilike(f"%{brand}%"))
    if in_stock_only:
        query = query.filter(HardwareProduct.in_stock == True)
    if featured_only:
        query = query.filter(HardwareProduct.is_featured == True)
    if popular_only:
        query = query.filter(HardwareProduct.is_popular == True)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                HardwareProduct.name.ilike(s),
                HardwareProduct.sku.ilike(s),
                HardwareProduct.brand.ilike(s),
                HardwareProduct.model_number.ilike(s),
                HardwareProduct.short_description.ilike(s)
            )
        )

    return (
        query.order_by(HardwareProduct.sort_order.asc(), HardwareProduct.is_popular.desc(), HardwareProduct.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/products/{product_id}", response_model=HardwareProductResponse)
def get_hardware_product(product_id: UUID, db: Session = Depends(get_db)):
    """
    Fetch comprehensive hardware product details including specifications, features, and images.
    """
    product = db.query(HardwareProduct).filter(HardwareProduct.id == product_id).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Hardware product not found")
    return product


@router.post("/products", response_model=HardwareProductResponse, status_code=status.HTTP_201_CREATED)
def create_hardware_product(
    payload: HardwareProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    List a new hardware product in the marketplace (Admin only).
    """
    existing = db.query(HardwareProduct).filter(HardwareProduct.sku == payload.sku).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Product with SKU '{payload.sku}' already exists")

    # Compute discount % if MRP is provided
    discount_val = payload.discount_pct
    if payload.mrp and payload.mrp > payload.price and discount_val == 0:
        discount_val = (((payload.mrp - payload.price) / payload.mrp) * Decimal("100")).quantize(Decimal("0.01"))

    product = HardwareProduct(
        sku=payload.sku.strip().upper(),
        name=payload.name,
        category=payload.category.strip().upper(),
        brand=payload.brand,
        model_number=payload.model_number,
        short_description=payload.short_description,
        description=payload.description,
        specifications=payload.specifications or {},
        features=payload.features or [],
        price=payload.price,
        mrp=payload.mrp,
        discount_pct=discount_val,
        tax_rate=payload.tax_rate,
        primary_image_url=payload.primary_image_url,
        images=payload.images or [],
        stock_quantity=payload.stock_quantity,
        in_stock=payload.in_stock,
        warranty_months=payload.warranty_months,
        is_popular=payload.is_popular,
        is_featured=payload.is_featured,
        is_active=payload.is_active,
        sort_order=payload.sort_order
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=HardwareProductResponse)
def update_hardware_product(
    product_id: UUID,
    payload: HardwareProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Update hardware product pricing, stock quantity, images, or specs (Admin only).
    """
    product = db.query(HardwareProduct).filter(HardwareProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Hardware product not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    # Recompute discount % if price or mrp changed
    if product.mrp and product.mrp > product.price:
        product.discount_pct = (((product.mrp - product.price) / product.mrp) * Decimal("100")).quantize(Decimal("0.01"))

    # Auto sync in_stock boolean with stock_quantity
    if product.stock_quantity <= 0:
        product.in_stock = False

    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hardware_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Soft-delete a hardware product from the active listing.
    """
    product = db.query(HardwareProduct).filter(HardwareProduct.id == product_id).first()
    if product:
        product.is_active = False
        db.commit()
    return None


# ============================================================================
# Hardware Purchase & Orders Endpoints
# ============================================================================
@router.post("/orders", response_model=HardwareOrderResponse, status_code=status.HTTP_201_CREATED)
def place_hardware_order(
    payload: HardwareOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Place a hardware purchase order / request a demo inquiry directly from the restaurant dashboard.
    """
    product = db.query(HardwareProduct).filter(HardwareProduct.id == payload.product_id).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Hardware product not available")

    # Generate sequential order code
    date_str = datetime.utcnow().strftime("%Y%m")
    count_today = db.query(HardwareOrder).count() + 1
    order_code = f"HWO-{date_str}-{count_today:04d}"

    total_amount = (product.price * payload.quantity).quantize(Decimal("0.01"))

    order = HardwareOrder(
        tenant_id=current_user.tenant_id,
        outlet_id=payload.outlet_id or current_user.outlet_id,
        product_id=product.id,
        order_number=order_code,
        quantity=payload.quantity,
        unit_price=product.price,
        total_price=total_amount,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        shipping_address=payload.shipping_address,
        city=payload.city,
        state=payload.state,
        pincode=payload.pincode,
        payment_method=payload.payment_method,
        status="NEW",
        payment_status="PENDING",
        notes=payload.notes
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/orders", response_model=List[HardwareOrderResponse])
def get_hardware_orders(
    status_filter: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    List hardware orders placed by this tenant or outlet.
    """
    query = db.query(HardwareOrder)
    if current_user.tenant_id:
        query = query.filter(HardwareOrder.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.filter(HardwareOrder.status == status_filter.upper())

    return query.order_by(HardwareOrder.created_at.desc()).limit(limit).all()


@router.get("/orders/{order_id}", response_model=HardwareOrderResponse)
def get_hardware_order(
    order_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Get hardware order status, tracking number, and dispatch progress.
    """
    order = db.query(HardwareOrder).filter(HardwareOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Hardware order not found")
    return order


@router.patch("/orders/{order_id}", response_model=HardwareOrderResponse)
def update_hardware_order(
    order_id: UUID,
    payload: HardwareOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Update hardware order fulfillment status, courier partner, or tracking number (Admin).
    """
    order = db.query(HardwareOrder).filter(HardwareOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Hardware order not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)
    return order


# ============================================================================
# Seed Initial Curated Restaurant Hardware Catalog
# ============================================================================
DEFAULT_SEED_PRODUCTS = [
    {
        "sku": "SB-PRN-80MM-PRO",
        "name": "SirfBill 80mm High-Speed Thermal Receipt & KOT Printer",
        "category": "PRINTER",
        "brand": "SirfBill",
        "model_number": "SB-80T Pro",
        "short_description": "Triple Interface (USB + LAN + Bluetooth) thermal printer with 260mm/s print speed and heavy-duty auto cutter.",
        "description": "Engineered specifically for heavy restaurant kitchen grease environments and ultra-fast counter billing. Features drop-in paper loading, audible beep buzzer on KOT arrival, and direct RJ11 cash drawer trigger.",
        "specifications": {
            "print_speed": "260 mm/sec",
            "paper_width": "80mm (3.15 inch)",
            "interfaces": ["USB 2.0", "Ethernet / LAN (RJ45)", "Bluetooth 4.2", "Cash Drawer (RJ11)"],
            "cutter_life": "1.5 Million cuts",
            "printhead_life": "150 KM",
            "command_set": "ESC / POS Compatible",
            "resolution": "203 DPI (8 dots/mm)",
            "os_compatibility": ["Android", "Windows 10/11", "iOS", "Linux", "macOS"]
        },
        "features": [
            "Triple connectivity: Print simultaneously over LAN from multiple Waiter Tablets and USB POS",
            "Built-in automatic paper cutter (partial and full cut)",
            "Loud acoustic buzzer and LED warning for noisy kitchen environments",
            "Direct plug-and-play with SirfBill POS with zero driver configuration",
            "1 Year Full Brand Replacement Warranty with doorstep pickup"
        ],
        "price": Decimal("5499.00"),
        "mrp": Decimal("7999.00"),
        "discount_pct": Decimal("31.25"),
        "tax_rate": Decimal("18.00"),
        "primary_image_url": "https://images.unsplash.com/photo-1612815154858-60aa4c59eaa6?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1612815154858-60aa4c59eaa6?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 85,
        "warranty_months": 12,
        "is_popular": True,
        "is_featured": True,
        "sort_order": 1
    },
    {
        "sku": "SB-POS-156-DUAL",
        "name": "SirfBill All-in-One 15.6-inch Dual Screen Touch POS Terminal",
        "category": "POS_TERMINAL",
        "brand": "SirfBill",
        "model_number": "SB-T15 Dual",
        "short_description": "Commercial True-Flat PCAP Touch Terminal with 15.6\" Cashier Display + 10.1\" Customer Facing Ad/QR Screen.",
        "description": "High-performance billing computer built for heavy continuous 24/7 restaurant operations. Quad-Core J4125 processor, 8GB DDR4 RAM, 128GB High-Speed SSD, and aluminum alloy die-cast stand.",
        "specifications": {
            "main_display": "15.6 inch Full HD (1920x1080) Projected Capacitive Touch",
            "secondary_display": "10.1 inch Customer Screen for dynamic UPI QR, Bill Review & Ads",
            "processor": "Intel Celeron Quad-Core J4125 (up to 2.7 GHz)",
            "ram": "8 GB DDR4",
            "storage": "128 GB M.2 NVMe SSD",
            "ports": ["6x USB", "1x LAN RJ45", "1x HDMI", "1x COM / RS232", "1x Audio Out"],
            "stand": "Heavy-duty Aluminum Alloy Die-Cast Stand (Anti-vibration)",
            "os": "Windows 11 Pro 64-bit Pre-activated / SirfBill Desktop POS Pre-installed"
        },
        "features": [
            "Customer-facing screen displays live cart itemization and Dynamic Bharat UPI QR",
            "Waterproof, dustproof, and grease-resistant front touch bezel (IP54 rated)",
            "Fanless silent cooling architecture prevents kitchen flour and oil dust ingress",
            "Includes pre-installed SirfBill Restaurant POS Suite",
            "1 Year On-site Manufacturer Warranty"
        ],
        "price": Decimal("28999.00"),
        "mrp": Decimal("38000.00"),
        "discount_pct": Decimal("23.69"),
        "tax_rate": Decimal("18.00"),
        "primary_image_url": "https://images.unsplash.com/photo-1556742049-0a67c5574f73?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1556742049-0a67c5574f73?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 25,
        "warranty_months": 12,
        "is_popular": True,
        "is_featured": True,
        "sort_order": 2
    },
    {
        "sku": "SB-PDA-WTR-55",
        "name": "SirfBill 5.5-inch Handheld Captain Tablet with Built-in 58mm Printer",
        "category": "HANDHELD_PDA",
        "brand": "SirfBill",
        "model_number": "SB-PDA V2",
        "short_description": "Wireless Android 12 Captain Ordering Terminal with integrated 58mm high-speed receipt printer and 4G/WiFi.",
        "description": "Empower your captains and waiters to take orders table-side, select modifiers, trigger instant KOT printing, and accept UPI QR payments right at the guest's dining table.",
        "specifications": {
            "screen": "5.5 inch HD IPS Touchscreen (1440x720)",
            "os": "Android 12 with GMS Certification",
            "printer": "Integrated 58mm Thermal Printer (70 mm/sec speed)",
            "battery": "5000 mAh Li-Ion (12 Hours continuous shift operation)",
            "connectivity": ["Dual Band Wi-Fi 2.4G/5G", "4G LTE Dual SIM", "Bluetooth 5.0", "Type-C Fast Charge"],
            "camera": "5.0 MP Rear Camera with Flash for quick QR / Barcode scanning"
        },
        "features": [
            "Table-side ordering and instant bill printing from the waiter's pocket",
            "Ultra-long 5000mAh battery handles double lunch/dinner shifts without recharging",
            "Drop-tested to 1.5 meters onto concrete floor with rubberized bumper edges",
            "1 Year Brand Warranty"
        ],
        "price": Decimal("11499.00"),
        "mrp": Decimal("16500.00"),
        "discount_pct": Decimal("30.31"),
        "tax_rate": Decimal("18.00"),
        "primary_image_url": "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 40,
        "warranty_months": 12,
        "is_popular": True,
        "is_featured": True,
        "sort_order": 3
    },
    {
        "sku": "SB-CSH-DWR-RJ11",
        "name": "SirfBill Heavy-Duty Electronic Cash Drawer (RJ11 Trigger)",
        "category": "CASH_DRAWER",
        "brand": "SirfBill",
        "model_number": "SB-CD410",
        "short_description": "Steel construction cash drawer with 5 Currency Bill compartments, 8 Coin cups, and 3-position security key lock.",
        "description": "Plugs directly into your thermal receipt printer via RJ11 telephone jack. Automatically pops open whenever a cash bill is settled from SirfBill POS.",
        "specifications": {
            "dimensions": "410mm (W) x 420mm (D) x 100mm (H)",
            "construction": "Thick gauge cold-rolled steel with scratch-resistant powder coating",
            "trays": "5 Bill Compartments with metal wire clips + 8 Removable Coin Cups",
            "lock": "3-Position Key Lock (Manual Open, Electric Auto-Trigger, Lock)",
            "interface": "RJ11 / RJ12 6-pin connector (24V compatible with 80mm printers)",
            "durability": "1 Million+ open/close cycles"
        },
        "features": [
            "Auto-pops open on cash invoice print; remains locked on digital/card payments",
            "Includes media slot on front bezel for inserting credit card slips and cheques without opening drawer",
            "Supplied with 2 physical brass security keys",
            "1 Year Replacement Warranty"
        ],
        "price": Decimal("2799.00"),
        "mrp": Decimal("4200.00"),
        "discount_pct": Decimal("33.36"),
        "tax_rate": Decimal("18.00"),
        "primary_image_url": "https://images.unsplash.com/photo-1556742044-3c52d6e88c62?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1556742044-3c52d6e88c62?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 60,
        "warranty_months": 12,
        "is_popular": False,
        "is_featured": False,
        "sort_order": 4
    },
    {
        "sku": "SB-SCN-2D-WLS",
        "name": "SirfBill Wireless 2D Barcode & QR Code Scanner with Charging Cradle",
        "category": "SCANNER",
        "brand": "SirfBill",
        "model_number": "SB-SC200W",
        "short_description": "2.4GHz Wireless + Bluetooth 1D/2D QR scanner with 100m range and smart induction charging cradle.",
        "description": "Reads printed barcodes as well as smartphone screen QR codes (such as payment receipts and loyalty member IDs) instantly with zero lag.",
        "specifications": {
            "optical_sensor": "CMOS 640x480 Global Shutter",
            "decoding_capability": "1D: Code 128, EAN-13, UPC; 2D: QR Code, Data Matrix, PDF417",
            "wireless_range": "Up to 100 meters (2.4GHz) / 30 meters (Bluetooth)",
            "battery": "2000 mAh rechargeable battery (Up to 30,000 scans per charge)",
            "cradle": "Automatic smart pairing cradle with USB interface"
        },
        "features": [
            "Instant scan from guest phone screens (e.g. member QR code, coupon vouchers)",
            "Auto-sensing hands-free presentation mode on stand",
            "Rugged anti-shock design survives drops up to 2 meters",
            "1 Year Replacement Warranty"
        ],
        "price": Decimal("2499.00"),
        "mrp": Decimal("3999.00"),
        "discount_pct": Decimal("37.51"),
        "tax_rate": Decimal("18.00"),
        "primary_image_url": "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 70,
        "warranty_months": 12,
        "is_popular": False,
        "is_featured": False,
        "sort_order": 5
    },
    {
        "sku": "SB-PPR-80MM-BOX50",
        "name": "SirfBill Premium 80mm Thermal Paper Rolls (Box of 50 Rolls)",
        "category": "PAPER_ROLLS",
        "brand": "SirfBill",
        "model_number": "SB-P80-50",
        "short_description": "BPA-Free 80mm x 50-meter ultra-white high-density thermal paper rolls with 5-year image durability.",
        "description": "Specially formulated thermal coating protects your thermal printhead from abrasion and delivers jet-black text and sharp QR codes on every invoice.",
        "specifications": {
            "roll_width": "80mm (3-inch)",
            "roll_length": "50 meters per roll",
            "paper_weight": "55 GSM high-grade woodfree thermal paper",
            "box_quantity": "50 Rolls per sealed carton",
            "coating": "BPA-Free, Dust-free, Moisture-proof inner foil wrap",
            "image_retention": "Up to 5 years under indoor storage"
        },
        "features": [
            "Red end-of-roll warning stripe indicates when paper is running low",
            "Jam-free smooth winding prevents thermal printer gear slippage",
            "High thermal sensitivity yields dark black text with minimal printer energy",
            "Free doorstep delivery on carton box orders"
        ],
        "price": Decimal("1899.00"),
        "mrp": Decimal("2500.00"),
        "discount_pct": Decimal("24.04"),
        "tax_rate": Decimal("12.00"), # 12% GST on paper consumables
        "primary_image_url": "https://images.unsplash.com/photo-1607344645866-009c320b5ab8?w=800&auto=format&fit=crop&q=80",
        "images": [
            "https://images.unsplash.com/photo-1607344645866-009c320b5ab8?w=800&auto=format&fit=crop&q=80"
        ],
        "stock_quantity": 200,
        "warranty_months": 0,
        "is_popular": True,
        "is_featured": False,
        "sort_order": 6
    }
]

@router.post("/seed", response_model=dict)
def seed_hardware_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_manager)
):
    """
    Seed initial curated restaurant hardware products if not already present.
    """
    seeded_count = 0
    for item_data in DEFAULT_SEED_PRODUCTS:
        existing = db.query(HardwareProduct).filter(HardwareProduct.sku == item_data["sku"]).first()
        if not existing:
            product = HardwareProduct(**item_data)
            db.add(product)
            seeded_count += 1

    db.commit()
    return {
        "status": "SUCCESS",
        "message": f"Successfully seeded {seeded_count} hardware products into catalog.",
        "total_seeded": seeded_count
    }
