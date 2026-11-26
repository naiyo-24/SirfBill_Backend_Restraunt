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
        phone="+919999900001",
        name="Branch Test Admin",
        email=f"admin_{uuid.uuid4().hex[:6]}@test.com",
        password="password123",
        is_active=True
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    # Override get_optional_current_user and get_admin_user dependencies
    from dependencies import get_optional_current_user, get_admin_user, get_restaurant_manager
    app.dependency_overrides[get_optional_current_user] = lambda: admin_user
    app.dependency_overrides[get_admin_user] = lambda: admin_user
    app.dependency_overrides[get_restaurant_manager] = lambda: admin_user

    # 2. Create Branch 1 (Primary)
    print("\n--- 2. Creating Branch 1 (Primary) ---")
    code1 = f"SL_{uuid.uuid4().hex[:5]}"
    resp1 = client.post("/api/admin/shop", json={
        "name": "Taste of Bengal: Salt Lake",
        "code": code1,
        "address": "Sector 5, Salt Lake, Kolkata",
        "city": "Kolkata",
        "contact_number": "+919876543201",
        "status": "Active",
        "is_primary": True
    })
    assert resp1.status_code == 201, f"Failed to create Branch 1: {resp1.text}"
    branch1_data = resp1.json()
    branch1_id = uuid.UUID(branch1_data["id"])
    print(f"[PASS] Branch 1 created: {branch1_data['name']} (ID: {branch1_id})")

    # Verify Branch 1 has active onboarding subscription
    status1_resp = client.get(f"/api/subscriptions/status?outlet_id={branch1_id}")
    assert status1_resp.status_code == 200, f"Failed status check: {status1_resp.text}"
    status1 = status1_resp.json()
    print(f"[STATUS Branch 1] status: {status1['status']}, is_active: {status1['is_active']}, days: {status1['days_remaining']}")
    assert status1["is_active"] == True, "Branch 1 should have active subscription"

    # 3. Create Branch 2 (Additional Branch)
    print("\n--- 3. Creating Branch 2 (Additional Branch) ---")
    code2 = f"NT_{uuid.uuid4().hex[:5]}"
    resp2 = client.post("/api/admin/shop", json={
        "name": "Taste of Bengal: New Town",
        "code": code2,
        "address": "Action Area 1, New Town, Kolkata",
        "city": "Kolkata",
        "contact_number": "+919876543202",
        "status": "Active",
        "is_primary": False
    })
    assert resp2.status_code == 201, f"Failed to create Branch 2: {resp2.text}"
    branch2_data = resp2.json()
    branch2_id = uuid.UUID(branch2_data["id"])
    print(f"[PASS] Branch 2 created: {branch2_data['name']} (ID: {branch2_id})")

    # Verify Branch 2 starts in PENDING_PAYMENT / UNPAID and NOT Active
    status2_resp = client.get(f"/api/subscriptions/status?outlet_id={branch2_id}")
    assert status2_resp.status_code == 200, f"Failed status check: {status2_resp.text}"
    status2 = status2_resp.json()
    print(f"[STATUS Branch 2] status: {status2['status']}, is_active: {status2['is_active']}, days: {status2['days_remaining']}")
    assert status2["is_active"] == False, "Branch 2 MUST NOT be active until paid!"
    assert status2["status"] in ("PENDING_PAYMENT", "UNPAID"), f"Expected PENDING_PAYMENT or UNPAID, got: {status2['status']}"

    # 4. Check All Branches Overview
    print("\n--- 4. Testing GET /api/subscriptions/branches (All Branches Overview) ---")
    branches_resp = client.get("/api/subscriptions/branches")
    assert branches_resp.status_code == 200, f"Failed branches endpoint: {branches_resp.text}"
    branches = branches_resp.json()
    assert len(branches) == 2, f"Expected 2 branches, got {len(branches)}"
    
    b1_info = next(b for b in branches if b["outlet_id"] == str(branch1_id))
    b2_info = next(b for b in branches if b["outlet_id"] == str(branch2_id))
    
    print(f"[Branch 1 Overview] {b1_info['outlet_name']}: Status={b1_info['status']}, Active={b1_info['is_active']}, Days={b1_info['days_remaining']}")
    print(f"[Branch 2 Overview] {b2_info['outlet_name']}: Status={b2_info['status']}, Active={b2_info['is_active']}, Days={b2_info['days_remaining']}")
    assert b1_info["is_active"] == True
    assert b2_info["is_active"] == False

    # 5. Subscribe / Renew specifically for Branch 2
    print("\n--- 5. Subscribing / Renewing specifically for Branch 2 ---")
    sub2_resp = client.post("/api/subscriptions/subscribe", json={
        "outlet_id": str(branch2_id),
        "duration_months": 1,
        "payment_method": "UPI",
        "payment_reference": "TEST-UPI-BRANCH2-001"
    })
    assert sub2_resp.status_code == 201, f"Failed to subscribe Branch 2: {sub2_resp.text}"
    sub2_data = sub2_resp.json()
    print(f"[PASS] Subscribed Branch 2: Status={sub2_data['status']}, Days={sub2_data['days_remaining']}, Invoice={sub2_data['invoice_number']}")
    assert sub2_data["is_active"] == True
    assert sub2_data["outlet_id"] == str(branch2_id)

    # 6. Re-check Branch 2 Status
    status2_after = client.get(f"/api/subscriptions/status?outlet_id={branch2_id}").json()
    print(f"[STATUS Branch 2 After Payment] status: {status2_after['status']}, is_active: {status2_after['is_active']}, days: {status2_after['days_remaining']}")
    assert status2_after["is_active"] == True, "Branch 2 should now be ACTIVE!"
    assert status2_after["days_remaining"] >= 29

    # 7. Verify Invoices are Scoped per Branch
    print("\n--- 7. Verifying Branch Invoices ---")
    inv_b1 = client.get(f"/api/subscriptions/invoices?outlet_id={branch1_id}").json()
    inv_b2 = client.get(f"/api/subscriptions/invoices?outlet_id={branch2_id}").json()
    print(f"Branch 1 invoices: {len(inv_b1)} | Branch 2 invoices: {len(inv_b2)}")
    assert len(inv_b2) >= 1
    assert inv_b2[0]["outlet_id"] == str(branch2_id)

    print("\n=======================================================")
    print("ALL PER-BRANCH SUBSCRIPTION TESTS PASSED SUCCESSFULLY!")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
