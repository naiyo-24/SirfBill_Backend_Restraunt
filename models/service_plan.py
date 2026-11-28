import uuid
from sqlalchemy import Column, String, DateTime, Boolean, Numeric, Integer, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID

from .database import Base
from utils.timezone import get_current_time


class ServicePlan(Base):
    """
    Catalog of Add-on Growth & Marketing Services:
    - INFLUENCER_MARKETING (1, 2, 5, 11 Influencers)
    - RESTAURANT_WEBSITE (Basic, Standard, Customized, Business Plan)
    """
    __tablename__ = "service_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    category = Column(String(50), nullable=False, index=True)  # INFLUENCER_MARKETING, RESTAURANT_WEBSITE
    plan_code = Column(String(50), unique=True, nullable=False, index=True)
    badge = Column(String(50), nullable=True)  # STARTER, POPULAR, BEST VALUE, etc.
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False)
    gst_applicable = Column(Boolean, default=False, nullable=False)
    gst_rate = Column(Numeric(5, 2), default=18.00, nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    features = Column(JSON, default=list, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=get_current_time, nullable=False)
    updated_at = Column(DateTime, default=get_current_time, onupdate=get_current_time, nullable=False)
