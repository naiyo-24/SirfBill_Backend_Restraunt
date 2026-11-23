import random
import httpx
import os
import sys
import jwt
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from uuid import UUID

from models.database import get_db
from models.user import User
from models.otp import OTPStore
from schemas.auth import SendOTPRequest, VerifyOTPRequest, AdminLoginRequest, LogoutRequest

from dependencies import SECRET_KEY, ALGORITHM, get_current_user, optional_security

logger = logging.getLogger("uvicorn")

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 1 week

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)

@router.post("/send-otp")
async def send_otp(request: SendOTPRequest, db: Session = Depends(get_db)):
    """
    Step 1: Generates a random OTP, saves it to the DB, and sends it via APITXT.
    """
    # 1. Generate a random 4-digit OTP
    generated_otp = str(random.randint(1000, 9999))
    
    # 2. Save/Update the OTP in our database with a 5-minute expiration
    expiration_time = datetime.utcnow() + timedelta(minutes=5)
    
    existing_otp = db.query(OTPStore).filter(OTPStore.phone == request.phone).first()
    if existing_otp:
        existing_otp.otp_code = generated_otp
        existing_otp.expires_at = expiration_time
    else:
        new_otp = OTPStore(phone=request.phone, otp_code=generated_otp, expires_at=expiration_time)
        db.add(new_otp)
    
    db.commit()

    # ==========================================
    # 🧪 TESTING MODE: BYPASS APITXT
    # ==========================================
    TEST_NUMBERS = ["919999999999", "918888888888"]
    
    if request.phone in TEST_NUMBERS:
        db_otp = db.query(OTPStore).filter(OTPStore.phone == request.phone).first()
        db_otp.otp_code = "1234"
        db.commit()
        
        print(f"🛠️ APP STORE TEST MODE: Bypassed APITXT for {request.phone}. Use OTP: 1234")
        return {"message": "Test OTP mapped successfully"}
        
    # 3. Send the OTP using APITXT API (Production)
    apitxt_url = "https://apitxt.com/api/sendOTP"
    apitxt_auth_key = os.getenv("APITXT_AUTH_KEY", "YOUR_AUTH_KEY_HERE")
    
    payload = {
        "authkey": apitxt_auth_key,
        "mobile": request.phone,
        "otp": generated_otp,
        "channel": request.channel,
        "country": "91"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(apitxt_url, data=payload)
            response_data = response.json()
            
            if response_data.get("status") == "success":
                return {"message": f"OTP sent successfully via {request.channel}"}
            else:
                print("APITXT Error:", response_data)
                raise HTTPException(status_code=500, detail="Failed to send OTP via provider")
                
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Error connecting to SMS provider: {str(e)}")

@router.post("/verify-otp")
def verify_otp(request: VerifyOTPRequest, db: Session = Depends(get_db)):
    """
    Step 2: Checks if the OTP matches. If valid, logs the user in (or creates their account).
    """
    # 1. Find the OTP record in the database
    db_otp = db.query(OTPStore).filter(OTPStore.phone == request.phone).first()
    
    if not db_otp:
        raise HTTPException(status_code=400, detail="No OTP requested for this number")
        
    # 2. Check if OTP is expired
    if datetime.utcnow() > db_otp.expires_at:
        db.delete(db_otp)
        db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")
        
    # 3. Check if OTP matches
    if db_otp.otp_code != request.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    # 4. Success! OTP is valid. Clean it up so it can't be reused.
    db.delete(db_otp)
    
    # 5. Check if this is an existing user or a new registration
    user = db.query(User).filter(User.phone == request.phone).first()
    
    if not user:
        # Create a new user if they don't exist
        from models.restaurant_outlet import RestaurantOutlet
        active_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id.isnot(None)).first()
        def_tenant_id = active_outlet.tenant_id if active_outlet else None

        user = User(
            phone=request.phone,
            name=request.name,
            role="USER",
            tenant_id=def_tenant_id
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new_user = True
    else:
        if not user.tenant_id:
            from models.restaurant_outlet import RestaurantOutlet
            active_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.tenant_id.isnot(None)).first()
            if active_outlet and active_outlet.tenant_id:
                user.tenant_id = active_outlet.tenant_id
                db.commit()
                db.refresh(user)
        is_new_user = False

    # Generate JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    return {
        "message": "Login successful",
        "access_token": access_token,
        "user_id": str(user.id),
        "is_new_user": is_new_user,
        "role": user.role
    }

from models.restaurant_outlet import RestaurantOutlet

@router.post("/admin-login")
@router.post("/admin/login")
def admin_login(request: AdminLoginRequest, db: Session = Depends(get_db)):
    """
    Admin / Staff Login using Email and Password.
    Returns access token, user role, and assigned restaurant outlet info.
    """
    user = db.query(User).filter(User.email == request.email).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    role_upper = (user.role or "").upper()
    allowed_roles = ["ADMIN", "OWNER", "MANAGER", "CASHIER", "KITCHEN", "WAITER", "CHEF", "SUPER_ADMIN", "STAFF"]
    if role_upper not in allowed_roles:
        raise HTTPException(status_code=403, detail="You do not have access privileges")
        
    # Plain text password comparison (no hashing)
    if user.password != request.password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    # Generate JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    # Fetch assigned outlet or default to tenant/active outlet
    outlet = None
    if user.outlet_id:
        outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == user.outlet_id).first()
    if not outlet:
        outlet_query = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True)
        if user.tenant_id:
            outlet_query = outlet_query.filter(RestaurantOutlet.tenant_id == user.tenant_id)
        outlet = outlet_query.first() or db.query(RestaurantOutlet).first()

    # Self-heal missing tenant_id or orphan outlet_id on user
    updated = False
    if not user.tenant_id and outlet and outlet.tenant_id:
        user.tenant_id = outlet.tenant_id
        updated = True
    if outlet and user.outlet_id != outlet.id:
        existing_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == user.outlet_id).first() if user.outlet_id else None
        if not existing_outlet:
            user.outlet_id = outlet.id
            updated = True
    if updated:
        db.commit()
        db.refresh(user)

    resolved_outlet_id = str(outlet.id) if outlet else (str(user.outlet_id) if user.outlet_id else None)

    return {
        "message": "Admin Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "role": user.role,
        "name": user.name,
        "email": user.email,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "outlet_id": resolved_outlet_id,
        "assigned_outlet_id": resolved_outlet_id,
        "outlet": {
            "id": str(outlet.id) if outlet else None,
            "name": outlet.name if outlet else "SirfBill Grand Restaurant",
            "code": outlet.code if outlet else "SB-01"
        } if outlet else None
    }


@router.post("/logout")
@router.get("/logout")
@router.post("/admin-logout")
@router.post("/admin/logout")
async def logout(
    http_req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
):
    """
    Universal Staff / Admin / User Logout Endpoint.
    Validates token if provided, logs the logout event prominently in the terminal,
    records an audit event, and returns a clean success response.
    """
    body_data: Dict[str, Any] = {}
    try:
        if http_req.method in ["POST", "PUT", "PATCH"]:
            body_data = await http_req.json()
    except Exception:
        body_data = {}

    query_params = dict(http_req.query_params)

    # 1. Extract token from Authorization header or parameters
    token_str = None
    if credentials and credentials.credentials:
        token_str = credentials.credentials
    elif "authorization" in http_req.headers:
        auth_hdr = http_req.headers["authorization"]
        if auth_hdr.startswith("Bearer "):
            token_str = auth_hdr.split(" ", 1)[1].strip()
    elif "token" in query_params:
        token_str = query_params["token"]
    elif "token" in body_data:
        token_str = str(body_data["token"])

    # 2. Decode user from token if available
    user = None
    if token_str:
        try:
            payload = jwt.decode(token_str, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
        except Exception:
            pass

    # 3. Fallback to email or user_id from body or query
    email_param = body_data.get("email") or query_params.get("email")
    user_id_param = body_data.get("user_id") or query_params.get("user_id")

    if not user and email_param:
        user = db.query(User).filter(User.email == email_param).first()
    if not user and user_id_param:
        user = db.query(User).filter(User.id == user_id_param).first()

    user_email = user.email if user else (email_param or "Staff / Client Session")
    user_role = user.role if user else (body_data.get("role") or query_params.get("role") or "STAFF")
    panel_name = body_data.get("panel") or query_params.get("panel") or user_role or "PANEL"
    client_ip = http_req.client.host if http_req and http_req.client else "unknown"
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # High-visibility terminal output (shows in terminal & Docker stdout)
    banner = f"""
================================================================================
🔒 [USER LOGOUT] Time: {now_str}
   Panel: {panel_name.upper()} | User: {user_email} | Role: {user_role} | Client IP: {client_ip}
================================================================================
"""
    print(banner, flush=True)
    sys.stdout.flush()
    logger.info(f"[LOGOUT] User '{user_email}' ({user_role}) logged out from {panel_name} panel (IP: {client_ip}).")

    # Record persistent audit event in database
    try:
        from models.restaurant_audit import RestaurantAuditEvent
        from models.restaurant_outlet import RestaurantOutlet

        resolved_outlet_id = user.outlet_id if user and user.outlet_id else None
        resolved_tenant_id = user.tenant_id if user and user.tenant_id else None
        if not resolved_outlet_id or not resolved_tenant_id:
            default_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.is_active == True).first()
            if default_outlet:
                resolved_outlet_id = resolved_outlet_id or default_outlet.id
                resolved_tenant_id = resolved_tenant_id or default_outlet.tenant_id

        if resolved_outlet_id and resolved_tenant_id:
            audit = RestaurantAuditEvent(
                outlet_id=resolved_outlet_id,
                tenant_id=resolved_tenant_id,
                actor_id=user.id if user else None,
                action="USER_LOGOUT",
                entity_name="user",
                entity_id=str(user.id) if user else "session",
                reason=f"Logged out from {panel_name} panel (IP: {client_ip})"
            )
            db.add(audit)
            db.commit()
    except Exception as e:
        logger.warning(f"Could not write logout audit log: {e}")

    return {
        "status": "SUCCESS",
        "message": f"User {user_email} logged out successfully.",
        "user_email": user_email,
        "panel": panel_name,
        "role": user_role
    }


# Router aliases so any frontend URL variation reaches the logout handler
alias_router = APIRouter(tags=["Authentication Aliases"])

@alias_router.api_route("/api/restaurant/auth/logout", methods=["GET", "POST"])
@alias_router.api_route("/api/restaurant/logout", methods=["GET", "POST"])
@alias_router.api_route("/api/logout", methods=["GET", "POST"])
@alias_router.api_route("/auth/logout", methods=["GET", "POST"])
async def logout_alias_route(
    http_req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db)
):
    return await logout(http_req=http_req, credentials=credentials, db=db)
