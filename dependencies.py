import os
import jwt
from typing import Optional
from fastapi import Depends, HTTPException, status
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Returns the User if a valid Bearer token is passed; otherwise returns None (or fallback active staff).
    """
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            user_id: str = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    return user
        except Exception:
            pass

    # Fallback to first active admin/staff user in database for dev/kiosk POS terminals
    fallback = db.query(User).filter(User.role.in_(["ADMIN", "OWNER", "CASHIER", "MANAGER"])).first()
    return fallback

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
RESTAURANT_ROLES = ["ADMIN", "OWNER", "MANAGER", "CASHIER", "WAITER", "KITCHEN"]

def require_restaurant_roles(allowed_roles: list[str]):
    """
    Dependency factory to enforce restaurant-specific role access.
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles and current_user.role not in ["ADMIN", "OWNER"]:
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

def check_active_subscription(tenant_id, db: Session) -> bool:
    """
    Checks if a tenant currently has an active or trial subscription.
    Evaluates against authoritative local server time (IST - Asia/Kolkata).
    """
    from utils.timezone import get_current_time
    from models.restaurant_subscription import TenantSubscription

    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).order_by(TenantSubscription.expires_at.desc()).first()

    if not sub:
        return False

    now = get_current_time()
    # Active if expires_at is in the future and not cancelled
    return (sub.expires_at > now) and (sub.status != "CANCELLED")

def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency that enforces an active subscription.
    Throws HTTP 402 Payment Required if expired, triggering the payment screen across all modules.
    """
    tenant_id = current_user.tenant_id
    if not tenant_id and current_user.outlet_id:
        from models.restaurant_outlet import RestaurantOutlet
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == current_user.outlet_id).first()
        if outlet:
            tenant_id = outlet.tenant_id

    # If tenant has no active/trial subscription, block with 402 Payment Required
    if tenant_id and not check_active_subscription(tenant_id, db):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Subscription expired. Please renew your subscription plan (₹299/month) to continue using this module."
        )

    return current_user

