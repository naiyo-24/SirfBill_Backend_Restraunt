from typing import Optional, List
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_serializer

class StockTransferItemInput(BaseModel):
    ingredient_id: UUID
    destination_ingredient_id: Optional[UUID] = None
    quantity: Decimal = Field(..., gt=0, description="Quantity to transfer")
    input_uom: Optional[str] = "RECIPE" # "RECIPE" (e.g. GM) or "PURCHASE" (e.g. KG)
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = None

class StockTransferCreate(BaseModel):
    transfer_type: Optional[str] = "INTER_BRANCH" # "INTER_BRANCH" or "INTER_STATION"
    from_outlet_id: Optional[UUID] = None
    to_outlet_id: Optional[UUID] = None
    from_station: Optional[str] = "Central Store"
    to_station: Optional[str] = "Kitchen Main"
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    notes: Optional[str] = None
    items: List[StockTransferItemInput]

class StockTransferDispatchInput(BaseModel):
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    notes: Optional[str] = None
    sender_signature: Optional[str] = None
    driver_signature: Optional[str] = None

class StockTransferReceiveItemInput(BaseModel):
    item_id: UUID # id of the transfer item
    quantity_received: Decimal = Field(..., ge=0)
    input_uom: Optional[str] = "RECIPE" # "RECIPE" or "PURCHASE"
    variance_reason: Optional[str] = None # Mandatory if quantity_received < quantity_dispatched

class StockTransferReceiveInput(BaseModel):
    items: List[StockTransferReceiveItemInput]
    notes: Optional[str] = None
    receiver_signature: Optional[str] = None

class StockTransferItemResponse(BaseModel):
    id: UUID
    transfer_id: UUID
    ingredient_id: UUID
    destination_ingredient_id: Optional[UUID] = None
    ingredient_name: str
    sku: Optional[str] = None
    unit: str
    quantity_requested: Decimal
    quantity_dispatched: Decimal
    quantity_received: Decimal
    quantity_variance: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    variance_reason: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[date] = None
    created_at: datetime

    @field_serializer(
        "quantity_requested", "quantity_dispatched", "quantity_received",
        "quantity_variance", "unit_cost", "total_cost",
        check_fields=False
    )
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)

class StockTransferResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    transfer_number: str
    transfer_type: str
    from_outlet_id: UUID
    from_outlet_name: Optional[str] = None
    to_outlet_id: UUID
    to_outlet_name: Optional[str] = None
    from_station: Optional[str] = None
    to_station: Optional[str] = None
    status: str
    initiated_by_id: Optional[UUID] = None
    initiated_by_name: Optional[str] = None
    dispatched_by_id: Optional[UUID] = None
    dispatched_by_name: Optional[str] = None
    received_by_id: Optional[UUID] = None
    received_by_name: Optional[str] = None
    dispatched_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    sender_signature: Optional[str] = None
    driver_signature: Optional[str] = None
    receiver_signature: Optional[str] = None
    total_items: int
    total_valuation: Decimal
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[StockTransferItemResponse] = []

    # Frontend-friendly compatibility aliases
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    transfer_date: Optional[datetime] = None
    transferred_by: Optional[str] = None
    total_items_count: Optional[int] = None

    @field_serializer("total_valuation", check_fields=False)
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[float]:
        return float(v) if v is not None else None

    model_config = ConfigDict(from_attributes=True)
