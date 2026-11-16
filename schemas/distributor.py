from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
import re

class DistributorBase(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = Field(None, max_length=15)
    notes: Optional[str] = None
    is_active: bool = True

    @field_validator("gstin", mode="before")
    @classmethod
    def validate_gstin(cls, v):
        if v is None:
            return None
        cleaned = str(v).strip().upper()
        if not cleaned:
            return None
        # Remove any non-alphanumeric characters
        cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
        if len(cleaned) > 15:
            cleaned = cleaned[:15]
        return cleaned

class DistributorCreate(DistributorBase):
    shop_id: Optional[UUID] = None

class DistributorUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

class DistributorOut(DistributorBase):
    id: UUID
    shop_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
