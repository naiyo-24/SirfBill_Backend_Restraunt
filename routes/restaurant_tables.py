from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_table import RestaurantTable
from models.restaurant_order import RestaurantOrder
from schemas.restaurant_table import RestaurantTableCreate, RestaurantTableUpdate, RestaurantTableResponse
from dependencies import (
    get_restaurant_staff, get_restaurant_manager, get_optional_restaurant_staff,
    get_user_scoped_outlet_id
)

router = APIRouter(
    prefix="/api/restaurant/tables",
    tags=["Restaurant - Tables"]
)

@router.get("", response_model=List[RestaurantTableResponse])
def get_tables(
    outlet_id: Optional[UUID] = None,
    section: Optional[str] = None,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    List tables with live status (VACANT, OCCUPIED, RESERVED, CLEANING).
    Automatically maps active orders with their start time and amounts.
    """
    outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    if not outlet_id:
        return []

    query = (
        db.query(RestaurantTable)
        .filter(RestaurantTable.outlet_id == outlet_id)
        .filter(RestaurantTable.is_active == True)
    )
    if section:
        query = query.filter(RestaurantTable.section == section)
    if status_filter:
        query = query.filter(RestaurantTable.status == status_filter)
    tables = query.order_by(RestaurantTable.table_code.asc()).all()
    if not tables:
        return []

    # Map active orders for occupied tables (including OPEN, SENT_TO_KITCHEN, HOLD, SERVED awaiting settlement)
    active_orders = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.outlet_id == outlet_id)
        .filter(RestaurantOrder.table_id.isnot(None))
        .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "SERVED"]))
        .order_by(RestaurantOrder.created_at.asc())
        .all()
    )
    table_order_map = {o.table_id: o for o in active_orders}

    result = []
    for t in tables:
        t_resp = RestaurantTableResponse.model_validate(t)
        t_resp.table_number = t.table_code
        t_resp.floor = t.section
        active_o = table_order_map.get(t.id)
        if active_o:
            t_resp.status = "OCCUPIED"
            t_resp.active_order_id = active_o.id
            t_resp.active_order_number = active_o.order_number
            t_resp.active_order_status = active_o.status
            t_resp.active_order_created_at = active_o.created_at
            t_resp.active_order_grand_total = float(active_o.grand_total or 0.0)
        else:
            if t.status == "OCCUPIED":
                # No active order remaining for this table -> table is automatically VACANT
                t.status = "VACANT"
                db.commit()
                t_resp.status = "VACANT"
        result.append(t_resp)
    return result

@router.post("", response_model=RestaurantTableResponse, status_code=status.HTTP_201_CREATED)
def create_table(
    payload: RestaurantTableCreate,
    db: Session = Depends(get_db),
    manager_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    # Auto-resolve outlet_id strictly scoped to user tenant
    scoped_outlet_id = get_user_scoped_outlet_id(db, manager_user, payload.outlet_id)
    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == scoped_outlet_id).first() if scoped_outlet_id else None
    if not outlet:
        raise HTTPException(status_code=404, detail="No active restaurant outlet found to attach table to.")

    table_name = payload.table_number or payload.table_code or "T1"
    floor_name = payload.floor or payload.section or "Floor 1"
    table_status = (payload.status or "VACANT").upper()
    if table_status == "AVAILABLE":
        table_status = "VACANT"

    table = RestaurantTable(
        outlet_id=outlet.id,
        tenant_id=outlet.tenant_id,
        table_code=table_name,
        section=floor_name,
        capacity=payload.capacity,
        status=table_status,
        is_active=payload.is_active
    )
    db.add(table)
    db.commit()
    db.refresh(table)

    resp = RestaurantTableResponse.model_validate(table)
    resp.table_number = table.table_code
    resp.floor = table.section
    return resp

@router.put("/{table_id}", response_model=RestaurantTableResponse)
@router.patch("/{table_id}", response_model=RestaurantTableResponse)
def update_table(
    table_id: UUID,
    payload: RestaurantTableUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if payload.table_number:
        table.table_code = payload.table_number
    elif payload.table_code:
        table.table_code = payload.table_code

    if payload.floor:
        table.section = payload.floor
    elif payload.section:
        table.section = payload.section

    if payload.capacity is not None:
        table.capacity = payload.capacity

    if payload.status:
        st = payload.status.upper()
        if st in ["AVAILABLE", "VACANT", "CLEAN"]:
            st = "VACANT"
            # Cancel/clear any active order still lingering on this table
            active_orders = (
                db.query(RestaurantOrder)
                .filter(RestaurantOrder.table_id == table_id)
                .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "SERVED"]))
                .all()
            )
            for act_ord in active_orders:
                act_ord.status = "CANCELLED"
                act_ord.version += 1
        table.status = st

    if payload.is_active is not None:
        table.is_active = payload.is_active

    db.commit()
    db.refresh(table)

    resp = RestaurantTableResponse.model_validate(table)
    resp.table_number = table.table_code
    resp.floor = table.section
    return resp

@router.patch("/{table_id}/status", response_model=RestaurantTableResponse)
@router.put("/{table_id}/status", response_model=RestaurantTableResponse)
def update_table_status(
    table_id: UUID,
    payload: RestaurantTableUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if payload.status:
        st = payload.status.upper()
        if st in ["AVAILABLE", "VACANT", "CLEAN"]:
            st = "VACANT"
            # Cancel/clear any active order still lingering on this table
            active_orders = (
                db.query(RestaurantOrder)
                .filter(RestaurantOrder.table_id == table_id)
                .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "SERVED"]))
                .all()
            )
            for act_ord in active_orders:
                act_ord.status = "CANCELLED"
                act_ord.version += 1
        table.status = st

    db.commit()
    db.refresh(table)

    resp = RestaurantTableResponse.model_validate(table)
    resp.table_number = table.table_code
    resp.floor = table.section
    return resp

@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(
    table_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if table:
        db.delete(table)
        db.commit()
    return None

from schemas.restaurant_order import RestaurantOpenTableOrder, RestaurantOrderResponse
from models.restaurant_order import RestaurantOrder

@router.post("/{table_id}/open-order", response_model=RestaurantOrderResponse, status_code=status.HTTP_201_CREATED)
def open_table_order(
    table_id: UUID,
    payload: RestaurantOpenTableOrder,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_restaurant_staff)
):
    """
    Opens or resumes an active dine-in order for a specific table.
    Ensures no conflicting open orders exist on the same table.
    """
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    # Check for existing open order on this table
    existing_order = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.table_id == table_id)
        .filter(RestaurantOrder.status.in_(["OPEN", "SENT_TO_KITCHEN", "HOLD", "SERVED"]))
        .first()
    )
    if existing_order:
        if payload.customer_name and payload.customer_name != "Walk-in Guest":
            existing_order.customer_name = payload.customer_name
        if payload.customer_phone:
            existing_order.customer_phone = payload.customer_phone
        if payload.notes:
            existing_order.notes = payload.notes
        db.commit()
        db.refresh(existing_order)
        return existing_order

    # Generate sequential order number in IST
    from utils.timezone import get_current_time
    today_str = get_current_time().strftime("%Y%m%d")
    prefix = f"ORD-{today_str}-"
    count = (
        db.query(RestaurantOrder)
        .filter(RestaurantOrder.outlet_id == table.outlet_id)
        .filter(RestaurantOrder.order_number.like(f"{prefix}%"))
        .count()
    )
    order_num = f"{prefix}{count + 1:04d}"

    order = RestaurantOrder(
        outlet_id=table.outlet_id,
        tenant_id=table.tenant_id,
        order_number=order_num,
        order_type="DINE_IN",
        status="OPEN",
        table_id=table.id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        waiter_id=current_user.id,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
        version=1
    )
    db.add(order)
    table.status = "OCCUPIED"

    db.commit()
    db.refresh(order)
    return order


# --- Table QR Code Generation & Batch Retrieval ---
from fastapi.responses import Response
from schemas.restaurant_table import TableQRResponse, TableQRBatchResponse, TableQRBatchItem
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import CircleModuleDrawer, StyledPilQRModuleDrawer
from PIL import Image, ImageDraw
import io
import base64
import os

class _BlankEyeDrawer(StyledPilQRModuleDrawer):
    def drawrect(self, box, is_active):
        # Eyes will be custom drawn as smooth circular doughnut rings
        pass

def _render_styled_table_qr(
    qr_url: str,
    box_size: int = 18,
    border: int = 3,
    corner_radius: int = 40,
    style: str = "modern"
) -> bytes:
    """
    Renders high-definition QR code matching the modern pill-bar style:
    - Contiguous horizontal modules rendered as smooth rounded capsules/bars
    - Three corner finder eyes rendered as circular concentric doughnut rings
    - Anti-aliased high-resolution output with rounded card corners
    """
    if style == "classic":
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # 2x supersampling factor for ultra-crisp anti-aliasing
    SCALE = 2
    eff_box = box_size * SCALE
    eff_border = border * SCALE

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=eff_box,
        border=eff_border,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=CircleModuleDrawer(),
        eye_drawer=_BlankEyeDrawer()
    )

    pil_img = img._img.convert("RGBA")
    width_modules = qr.modules_count

    # Coordinates of 3 finder eyes
    eyes = [
        (eff_border * eff_box, eff_border * eff_box),
        ((eff_border + width_modules - 7) * eff_box, eff_border * eff_box),
        (eff_border * eff_box, (eff_border + width_modules - 7) * eff_box),
    ]

    eye_size = 7 * eff_box
    draw = ImageDraw.Draw(pil_img)

    for x, y in eyes:
        # Clear eye module zone to pure white
        draw.rectangle([x, y, x + eye_size, y + eye_size], fill=(255, 255, 255, 255))

        # Outer rounded-square ring: 7 modules
        draw.rounded_rectangle(
            [x, y, x + eye_size, y + eye_size],
            radius=int(2.2 * eff_box),
            fill=(0, 0, 0, 255)
        )

        # White rounded-square gap: 5 modules (margin of 1 module)
        m1 = eff_box
        draw.rounded_rectangle(
            [x + m1, y + m1, x + eye_size - m1, y + eye_size - m1],
            radius=int(1.4 * eff_box),
            fill=(255, 255, 255, 255)
        )

        # Inner solid circular pupil: 3 modules diameter (margin of 2 modules)
        m2 = 2 * eff_box
        draw.ellipse([x + m2, y + m2, x + eye_size - m2, y + eye_size - m2], fill=(0, 0, 0, 255))

    # Downsample back to target size for crisp anti-aliased curves
    final_w = pil_img.width // SCALE
    final_h = pil_img.height // SCALE
    final_img = pil_img.resize((final_w, final_h), Image.Resampling.LANCZOS)

    # Apply squircle rounded card corners
    mask = Image.new("L", (final_w, final_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, final_w - 1, final_h - 1], radius=corner_radius, fill=255)

    card_img = Image.new("RGBA", (final_w, final_h), (255, 255, 255, 0))
    card_img.paste(final_img, (0, 0), mask=mask)

    buf = io.BytesIO()
    card_img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_table_qr_data(
    table: RestaurantTable,
    outlet: Optional[RestaurantOutlet] = None,
    base_url: Optional[str] = None,
    style: str = "modern"
) -> tuple[str, str, bytes]:
    domain = base_url or os.getenv("FRONTEND_ORDER_URL", "")
    if not domain:
        domain = "http://localhost:59003"
    outlet_id_str = str(outlet.id) if outlet else str(table.outlet_id)
    qr_url = f"{domain.rstrip('/')}/#/table-order?outlet_id={outlet_id_str}&table_id={table.id}&code={table.table_code}"

    png_bytes = _render_styled_table_qr(qr_url, style=style)
    b64_str = f"data:image/png;base64,{base64.b64encode(png_bytes).decode('utf-8')}"
    return qr_url, b64_str, png_bytes


@router.get("/qr/batch", response_model=TableQRBatchResponse)
@router.get("/qr-batch", response_model=TableQRBatchResponse)
def get_batch_table_qrs(
    outlet_id: Optional[UUID] = None,
    base_url: Optional[str] = None,
    style: str = Query("modern", description="QR style: 'modern' (pill capsules & circular eyes) or 'classic'"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Returns batch QR codes for all tables in the restaurant outlet (useful for bulk standee printing).
    """
    scoped_outlet_id = get_user_scoped_outlet_id(db, current_user, outlet_id)
    if not scoped_outlet_id:
        raise HTTPException(status_code=400, detail="Outlet context required")

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == scoped_outlet_id).first()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")

    tables = db.query(RestaurantTable).filter(
        RestaurantTable.outlet_id == scoped_outlet_id,
        RestaurantTable.is_active == True
    ).order_by(RestaurantTable.table_code.asc()).all()

    items = []
    for t in tables:
        qr_url, b64_str, _ = _generate_table_qr_data(t, outlet, base_url, style=style)
        items.append(TableQRBatchItem(
            table_id=t.id,
            table_code=t.table_code,
            section=t.section,
            capacity=t.capacity,
            qr_url=qr_url,
            qr_image_base64=b64_str
        ))

    return TableQRBatchResponse(
        outlet_id=outlet.id,
        outlet_name=outlet.name,
        total_tables=len(items),
        tables=items
    )


@router.get("/{table_id}/qr", response_model=TableQRResponse)
def get_table_qr(
    table_id: UUID,
    base_url: Optional[str] = None,
    style: str = Query("modern", description="QR style: 'modern' (pill capsules & circular eyes) or 'classic'"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_restaurant_staff)
):
    """
    Returns the table's deep link and Base64-encoded QR image.
    Scanned by customer camera to auto-select table and open digital menu.
    """
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == table.outlet_id).first()
    outlet_name = outlet.name if outlet else "SirfBill Restaurant"

    qr_url, b64_str, _ = _generate_table_qr_data(table, outlet, base_url, style=style)
    return TableQRResponse(
        table_id=table.id,
        table_code=table.table_code,
        section=table.section,
        capacity=table.capacity,
        outlet_id=table.outlet_id,
        outlet_name=outlet_name,
        qr_url=qr_url,
        qr_image_base64=b64_str
    )


@router.get("/{table_id}/qr-image")
def get_table_qr_image(
    table_id: UUID,
    base_url: Optional[str] = None,
    style: str = Query("modern", description="QR style: 'modern' (pill capsules & circular eyes) or 'classic'"),
    db: Session = Depends(get_db)
):
    """
    Direct PNG image endpoint to display or download table QR code.
    """
    table = db.query(RestaurantTable).filter(RestaurantTable.id == table_id).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == table.outlet_id).first()
    _, _, png_bytes = _generate_table_qr_data(table, outlet, base_url, style=style)

    clean_code = table.table_code.replace(" ", "_")
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="table_{clean_code}_qr.png"'}
    )


