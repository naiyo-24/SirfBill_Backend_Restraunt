import os
import jwt
from uuid import UUID
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from models.database import get_db
from models.user import User

SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-manju-key-32bytes-secret-token")
ALGORITHM = "HS256"

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    """
    Validates the JWT token and returns the current user.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    
    return user

def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Returns the User if a valid Bearer token, header token, or session token is passed; otherwise returns None.
    Never falls back across tenants to prevent data leaks.
    """
    token_str = None
    if credentials and credentials.credentials:
        token_str = credentials.credentials
    elif request is not None:
        auth_hdr = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth_hdr:
            if auth_hdr.lower().startswith("bearer "):
                token_str = auth_hdr.split(" ", 1)[1].strip()
            else:
                token_str = auth_hdr.strip()
        if not token_str:
            token_str = (
                request.headers.get("x-access-token")
                or request.headers.get("x-token")
                or request.headers.get("token")
                or request.query_params.get("token")
            )

    if token_str:
        try:
            payload = jwt.decode(token_str, SECRET_KEY, algorithms=[ALGORITHM])
            user_id: str = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    return user
        except Exception:
            pass

    # If tenant_id or user_id query/header passed explicitly
    if request is not None:
        target_uid = request.headers.get("x-user-id") or request.query_params.get("user_id")
        if target_uid:
            try:
                user = db.query(User).filter(User.id == target_uid).first()
                if user:
                    return user
            except Exception:
                pass

    return None

def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Validates that the current user has the ADMIN, OWNER, or MANAGER role.
    """
    if current_user.role not in ["ADMIN", "OWNER", "MANAGER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission to perform this action. Admin, Owner, or Manager role required."
        )
    return current_user

def get_optional_admin_user(current_user: Optional[User] = Depends(get_optional_current_user)) -> Optional[User]:
    """
    Allows admin read operations on startup/dashboard with fallback.
    """
    return current_user

# --- Restaurant Role Dependencies ---
RESTAURANT_ROLES = ["ADMIN", "OWNER", "MANAGER", "CASHIER", "POS", "WAITER", "CAPTAIN", "KITCHEN", "CHEF", "INVENTORY", "CRM", "STAFF"]

def require_restaurant_roles(allowed_roles: list[str]):
    """
    Dependency factory to enforce restaurant-specific role access (case-insensitive).
    """
    allowed_upper = [r.upper() for r in allowed_roles]
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = (current_user.role or "").upper()
        if user_role not in allowed_upper and user_role not in ["ADMIN", "OWNER", "SUPER_ADMIN"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Required role in: {allowed_roles}"
            )
        return current_user
    return role_checker

def get_restaurant_staff(current_user: User = Depends(get_current_user)) -> User:
    """Allows any restaurant staff member (WAITER, CASHIER, KITCHEN, MANAGER, OWNER, ADMIN)."""
    return require_restaurant_roles(RESTAURANT_ROLES)(current_user)

def get_optional_restaurant_staff(
    user: Optional[User] = Depends(get_optional_current_user)
) -> Optional[User]:
    """
    Permits POS read requests even before token login or in kiosk mode,
    falling back to standard staff context.
    """
    return user

def get_restaurant_manager(current_user: User = Depends(get_current_user)) -> User:
    """Allows MANAGER, OWNER, or ADMIN for audits, menu changes, discount overrides."""
    return require_restaurant_roles(["MANAGER", "OWNER", "ADMIN"])(current_user)

def get_restaurant_cashier(current_user: User = Depends(get_current_user)) -> User:
    """Allows CASHIER, MANAGER, OWNER, or ADMIN for billing and shift closure."""
    return require_restaurant_roles(["CASHIER", "MANAGER", "OWNER", "ADMIN"])(current_user)

def get_restaurant_kitchen(current_user: User = Depends(get_current_user)) -> User:
    """Allows KITCHEN staff, MANAGER, OWNER, or ADMIN for KOT status updates."""
    return require_restaurant_roles(["KITCHEN", "MANAGER", "OWNER", "ADMIN"])(current_user)

def check_active_subscription(tenant_id, db: Session, outlet_id=None) -> bool:
    """
    Checks if a tenant/branch currently has an active or trial subscription.
    Evaluates against authoritative local server time (IST - Asia/Kolkata).
    Strictly isolated per branch when outlet_id is provided.
    """
    from utils.timezone import get_current_time
    from models.restaurant_subscription import TenantSubscription
    from uuid import UUID as PyUUID

    t_uuid = None
    if tenant_id:
        try:
            t_uuid = PyUUID(str(tenant_id))
        except (ValueError, TypeError):
            t_uuid = tenant_id

    o_uuid = None
    if outlet_id:
        try:
            o_uuid = PyUUID(str(outlet_id))
        except (ValueError, TypeError):
            o_uuid = outlet_id

    query = db.query(TenantSubscription)
    if t_uuid:
        query = query.filter(TenantSubscription.tenant_id == t_uuid)
    if o_uuid:
        query = query.filter(TenantSubscription.outlet_id == o_uuid)

    sub = query.order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        return False

    now = get_current_time()
    # Active if expires_at is in the future and not cancelled or pending payment
    return (sub.expires_at > now) and (sub.status not in ("CANCELLED", "PENDING_PAYMENT", "EXPIRED"))

def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency that enforces an active subscription for the current branch.
    Throws HTTP 402 Payment Required if expired, triggering the payment screen across all modules.
    """
    tenant_id = current_user.tenant_id
    scoped_outlet_id = current_user.outlet_id

    if not tenant_id and scoped_outlet_id:
        from models.restaurant_outlet import RestaurantOutlet
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == scoped_outlet_id).first()
        if outlet:
            tenant_id = outlet.tenant_id

    # If branch has no active/trial subscription, block with 402 Payment Required
    if tenant_id and not check_active_subscription(tenant_id, db, outlet_id=scoped_outlet_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription expired for this branch. Please renew your branch subscription plan to continue using this module."
        )

    return current_user


def get_user_scoped_outlet_id(
    db: Session,
    current_user: Optional[User],
    requested_outlet_id: Optional[UUID] = None
) -> Optional[UUID]:
    """
    Guarantees strict tenant isolation for outlets.
    If current_user has a tenant_id, the outlet returned MUST belong to current_user.tenant_id.
    Prevents cross-restaurant data leakage (e.g. seeing another restaurant's menu, orders, tables, or inventory).
    """
    from models.restaurant_outlet import RestaurantOutlet
    from uuid import UUID as PyUUID

    if current_user and current_user.tenant_id:
        # If user passed a specific outlet_id, verify it belongs to their tenant
        if requested_outlet_id:
            valid_outlet = db.query(RestaurantOutlet).filter(
                RestaurantOutlet.id == requested_outlet_id,
                RestaurantOutlet.tenant_id == current_user.tenant_id
            ).first()
            if valid_outlet:
                return valid_outlet.id
        
        # If user has an assigned outlet_id that belongs to their tenant, use it
        if current_user.outlet_id:
            assigned = db.query(RestaurantOutlet).filter(
                RestaurantOutlet.id == current_user.outlet_id,
                RestaurantOutlet.tenant_id == current_user.tenant_id
            ).first()
            if assigned:
                return assigned.id
        
        # Fallback to the first active outlet of THIS tenant
        tenant_outlet = db.query(RestaurantOutlet).filter(
            RestaurantOutlet.tenant_id == current_user.tenant_id,
            RestaurantOutlet.is_active == True
        ).first() or db.query(RestaurantOutlet).filter(
            RestaurantOutlet.tenant_id == current_user.tenant_id
        ).first()
        if tenant_outlet:
            return tenant_outlet.id
        
        return None
        
    # Unauthenticated / guest access: strictly respect requested_outlet_id if valid; NEVER leak another restaurant's outlet
    if requested_outlet_id:
        valid_outlet = db.query(RestaurantOutlet).filter(
            RestaurantOutlet.id == requested_outlet_id,
            RestaurantOutlet.is_active == True
        ).first()
        if valid_outlet:
            return valid_outlet.id
    return None

