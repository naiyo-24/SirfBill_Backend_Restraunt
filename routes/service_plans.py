from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID

from models.database import get_db
from models.service_plan import ServicePlan

router = APIRouter(
    prefix="/api/service-plans",
    tags=["Service Plans (Influencer Marketing & Website)"]
)


class ServicePlanResponse(BaseModel):
    id: UUID
    category: str
    plan_code: str
    badge: Optional[str] = None
    name: str
    description: Optional[str] = None
    price: float
    offer_price: Optional[float] = None
    gst_applicable: bool
    gst_rate: float
    currency: str
    features: List[str]
    sort_order: int
    is_active: bool

    class Config:
        from_attributes = True


@router.get("", response_model=List[ServicePlanResponse])
def list_service_plans(
    category: Optional[str] = Query(None, description="Filter by category: INFLUENCER_MARKETING or RESTAURANT_WEBSITE"),
    db: Session = Depends(get_db)
):
    query = db.query(ServicePlan).filter(ServicePlan.is_active == True)
    if category:
        query = query.filter(ServicePlan.category == category.upper())
    return query.order_by(ServicePlan.category.asc(), ServicePlan.sort_order.asc()).all()


@router.get("/{plan_code}", response_model=ServicePlanResponse)
def get_service_plan(plan_code: str, db: Session = Depends(get_db)):
    plan = db.query(ServicePlan).filter(ServicePlan.plan_code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Service plan not found")
    return plan
