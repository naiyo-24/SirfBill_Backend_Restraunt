import os
import sys
import uuid
from decimal import Decimal
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_subscription import TenantSubscription, SubscriptionPlan
from utils.timezone import get_current_time

client = TestClient(app)

def run_tests():
    db = next(get_db())
    test_tenant_id = uuid.uuid4()
    
    print(f"--- 1. Setting up Test Tenant: {test_tenant_id} ---")
    
    # 1. Create Admin User
    admin_user = User(
        id=uuid.uuid4(),
        tenant_id=test_tenant_id,
        role="ADMIN",
        phone="+919999900002",
        name="Security Test Admin",
        email=f"sec_admin_{uuid.uuid4().hex[:6]}@test.com",
        password="adminpassword123",
        is_active=True
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    # 2. Create Branch 1 (Active) & Branch 2 (Unpaid / Expired)
    from dependencies import get_optional_current_user, get_admin_user
    app.dependency_overrides[get_optional_current_user] = lambda: admin_user
    app.dependency_overrides[get_admin_user] = lambda: admin_user

    # Branch 1 (Primary - Active)
    resp1 = client.post("/api/admin/shop", json={
        "name": "Branch One Active",
        "code": f"b1_{uuid.uuid4().hex[:4]}",
        "address": "Address 1",
        "city": "Kolkata",
        "contact_number": "+919876543201",
        "status": "Active",
        "is_primary": True
    })
    assert resp1.status_code == 201
    branch1_id = uuid.UUID(resp1.json()["id"])
    b1_code = resp1.json()["code"]

    # Branch 2 (Additional - Unpaid/Expired)
    b2_code = f"b2_{uuid.uuid4().hex[:4]}"
    resp2 = client.post("/api/admin/shop", json={
        "name": "Branch Two Expired",
        "code": b2_code,
        "address": "Address 2",
        "city": "Kolkata",
        "contact_number": "+919876543202",
        "status": "Active",
        "is_primary": False
    })
    assert resp2.status_code == 201
    branch2_id = uuid.UUID(resp2.json()["id"])

    # Clear dependency overrides so login tests use real authentication
    app.dependency_overrides.clear()

    # Find the generated module accounts for Branch 2
    b2_pos_user = db.query(User).filter(User.outlet_id == branch2_id, User.role == "CASHIER").first()
    b2_kds_user = db.query(User).filter(User.outlet_id == branch2_id, User.role == "KITCHEN").first()
    b2_waiter_user = db.query(User).filter(User.outlet_id == branch2_id, User.role == "WAITER").first()
    b2_inv_user = db.query(User).filter(User.outlet_id == branch2_id, User.role == "MANAGER").first()

    assert b2_pos_user is not None, "Branch 2 POS user should exist"
    print(f"\nBranch 2 Cashier User: {b2_pos_user.email} (pass: {b2_pos_user.password})")

    # 3. TEST: Attempt login with Cashier ID and Password for expired Branch 2
    print("\n--- 3. Testing Login for Cashier on Expired Branch 2 ---")
    pos_login_resp = client.post("/api/auth/admin-login", json={
        "email": b2_pos_user.email,
        "password": b2_pos_user.password
    })
    print(f"Status: {pos_login_resp.status_code} | Body: {pos_login_resp.text}")
    assert pos_login_resp.status_code == 402, f"Expected 402 Payment Required, got {pos_login_resp.status_code}"
    assert "expired or is unpaid" in pos_login_resp.text
    print("[PASS] Cashier login correctly BLOCKED with HTTP 402 Payment Required!")

    # 4. TEST: Attempt login with Kitchen KDS for expired Branch 2
    print("\n--- 4. Testing Login for Kitchen KDS on Expired Branch 2 ---")
    kds_login_resp = client.post("/api/auth/admin-login", json={
        "email": b2_kds_user.email,
        "password": b2_kds_user.password
    })
    assert kds_login_resp.status_code == 402
    print("[PASS] Kitchen KDS login correctly BLOCKED with HTTP 402 Payment Required!")

    # 5. TEST: Attempt login with Waiter for expired Branch 2
    print("\n--- 5. Testing Login for Waiter on Expired Branch 2 ---")
    waiter_login_resp = client.post("/api/auth/admin-login", json={
        "email": b2_waiter_user.email,
        "password": b2_waiter_user.password
    })
    assert waiter_login_resp.status_code == 402
    print("[PASS] Waiter login correctly BLOCKED with HTTP 402 Payment Required!")

    # 6. TEST: Attempt login with Manager for expired Branch 2
    print("\n--- 6. Testing Login for Manager on Expired Branch 2 ---")
    inv_login_resp = client.post("/api/auth/admin-login", json={
        "email": b2_inv_user.email,
        "password": b2_inv_user.password
    })
    assert inv_login_resp.status_code == 402
    print("[PASS] Manager login correctly BLOCKED with HTTP 402 Payment Required!")

    # 7. TEST: Admin logging into Admin panel allowed, but POS terminal blocked
    print("\n--- 7. Testing Admin Login with POS Panel vs Admin Panel ---")
    admin_pos_resp = client.post("/api/auth/admin-login", json={
        "email": admin_user.email,
        "password": "adminpassword123",
        "outlet_id": str(branch2_id),
        "panel": "POS"
    })
    assert admin_pos_resp.status_code == 402
    print("[PASS] Admin logging into POS terminal for expired branch is BLOCKED with 402!")

    admin_panel_resp = client.post("/api/auth/admin-login", json={
        "email": admin_user.email,
        "password": "adminpassword123",
        "panel": "ADMIN"
    })
    assert admin_panel_resp.status_code == 200
    print("[PASS] Admin logging into Admin panel is ALLOWED so they can renew!")

    # 8. TEST: Direct order creation on expired Branch 2 is BLOCKED
    print("\n--- 8. Testing Direct Order Creation on Expired Branch 2 ---")
    app.dependency_overrides[get_optional_current_user] = lambda: admin_user
    order_fail_resp = client.post("/api/restaurant/orders", json={
        "outlet_id": str(branch2_id),
        "order_type": "DINE_IN",
        "items": []
    })
    print(f"Order create status: {order_fail_resp.status_code} | Body: {order_fail_resp.text}")
    assert order_fail_resp.status_code == 402
    print("[PASS] Order creation on expired branch BLOCKED with HTTP 402!")

    # 9. TEST: Activate / Subscribe Branch 2, then re-test Cashier login & order creation
    print("\n--- 9. Activating / Subscribing Branch 2 ---")
    sub_resp = client.post("/api/subscriptions/subscribe", json={
        "outlet_id": str(branch2_id),
        "duration_months": 1,
        "payment_method": "UPI",
        "payment_reference": "TEST-RENEW-001"
    })
    assert sub_resp.status_code == 201
    print("[PASS] Branch 2 subscribed successfully!")

    app.dependency_overrides.clear()
    pos_login_after = client.post("/api/auth/admin-login", json={
        "email": b2_pos_user.email,
        "password": b2_pos_user.password
    })
    assert pos_login_after.status_code == 200
    print("[PASS] Cashier can now log in successfully after branch subscription is active!")

    print("\n=======================================================")
    print("ALL EXPIRED BRANCH LOGIN BLOCK TESTS PASSED 100%!")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
