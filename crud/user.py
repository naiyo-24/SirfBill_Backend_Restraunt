from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from models.user import User
from schemas.user import UserCreate, UserUpdate

def get_user(db: Session, user_id: UUID) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_phone(db: Session, phone: str, tenant_id: Optional[UUID] = None) -> Optional[User]:
    query = db.query(User).filter(User.phone == phone)
    if tenant_id:
        query = query.filter(User.tenant_id == tenant_id)
    return query.first()

def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[User]:
    return db.query(User).offset(skip).limit(limit).all()

def create_user(db: Session, user: UserCreate, context_tenant_id: Optional[UUID] = None) -> User:
    from models.restaurant_outlet import RestaurantOutlet
    user_data = user.model_dump()
    if context_tenant_id:
        user_data["tenant_id"] = context_tenant_id

    # If tenant_id is missing, auto-resolve from outlet or active tenant
    if not user_data.get("tenant_id"):
        target_outlet = user_data.get("outlet_id") or user_data.get("branch_id")
        if target_outlet:
            outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == target_outlet).first()
            if outlet and outlet.tenant_id:
                user_data["tenant_id"] = outlet.tenant_id
        if not user_data.get("tenant_id"):
            active_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id.isnot(None)).first()
            if active_outlet:
                user_data["tenant_id"] = active_outlet.tenant_id

    db_user = User(**user_data)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, db_user: User, user_update: UserUpdate) -> User:
    from models.restaurant_outlet import RestaurantOutlet
    update_data = user_update.model_dump(exclude_unset=True)
    if "branch_id" in update_data and update_data.get("outlet_id") is None:
        update_data["outlet_id"] = update_data["branch_id"]
    if "shop_id" in update_data and update_data.get("outlet_id") is None:
        update_data["outlet_id"] = update_data["shop_id"]
    update_data.pop("branch_id", None)
    update_data.pop("shop_id", None)
    update_data.pop("branch_name", None)

    for key, value in update_data.items():
        if key == "role" and isinstance(value, str):
            value = value.upper()
        if hasattr(db_user, key):
            setattr(db_user, key, value)

    # Auto-resolve tenant_id if missing or if outlet was assigned
    if not db_user.tenant_id and db_user.outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == db_user.outlet_id).first()
        if outlet and outlet.tenant_id:
            db_user.tenant_id = outlet.tenant_id

    if not db_user.tenant_id:
        active_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id.isnot(None)).first()
        if active_outlet:
            db_user.tenant_id = active_outlet.tenant_id

    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user(db: Session, db_user: User) -> User:
    db.delete(db_user)
    db.commit()
    return db_user
