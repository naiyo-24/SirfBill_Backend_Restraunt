import uuid
from decimal import Decimal
from fastapi.testclient import TestClient
from main import app
from models.database import get_db
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_subscription import TenantSubscription

client = TestClient(app)

def test_new_admin_auto_provisioning_and_isolation():
    db = next(get_db())

    # 1. Simulate a new restaurant admin created in public.users without an outlet yet
    unique_id = uuid.uuid4().hex[:6]
    test_tenant_id = uuid.uuid4()
    admin_email = f"brothers_{unique_id}@test.com"
    admin_pass = "admin123"

    user = User(
        id=uuid.uuid4(),
        tenant_id=test_tenant_id,
        outlet_id=None,
        role="ADMIN",
        name="The Brothers Kitchen Admin",
        email=admin_email,
        phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        password=admin_pass,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    print(f"Created manual admin in DB: {admin_email} with tenant {test_tenant_id}")

    # 2. Test Admin Login
    login_resp = client.post("/api/auth/admin-login", json={
        "email": admin_email,
        "password": admin_pass
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    login_data = login_resp.json()
    token = login_data["access_token"]
    assigned_outlet_id = login_data["outlet_id"]
    assert assigned_outlet_id is not None, "Outlet ID should have been auto-provisioned!"

    # Verify that outlet was created in DB and subscription provisioned
    created_outlet = db.query(RestaurantOutlet).filter(RestaurantOutlet.id == assigned_outlet_id).first()
    assert created_outlet is not None
    assert created_outlet.tenant_id == test_tenant_id
    assert "Brothers Kitchen" in created_outlet.name
    print(f"✅ Auto-provisioned Outlet: {created_outlet.name} (id: {created_outlet.id})")

    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == test_tenant_id,
        TenantSubscription.outlet_id == assigned_outlet_id
    ).first()
    assert sub is not None
    assert sub.status == "ACTIVE"
    print(f"✅ Auto-provisioned Subscription: {sub.status} (expires: {sub.expires_at})")

    headers = {"Authorization": f"Bearer {token}"}

    # 3. Test GET /api/admin/shops and /api/restaurant/outlets - MUST ONLY return The Brothers Kitchen, NOT Naiyo24
    shops_resp = client.get("/api/admin/shops", headers=headers)
    assert shops_resp.status_code == 200
    shops = shops_resp.json()
    assert len(shops) == 1, f"Expected 1 outlet, got {len(shops)}"
    assert shops[0]["id"] == str(assigned_outlet_id)
    assert "Brothers Kitchen" in shops[0]["name"]
    print(f"✅ /api/admin/shops returned exactly 1 scoped outlet: {shops[0]['name']}")

    outlets_resp = client.get("/api/restaurant/outlets", headers=headers)
    assert outlets_resp.status_code == 200
    outlets = outlets_resp.json()
    assert len(outlets) == 1, f"Expected 1 outlet, got {len(outlets)}"
    assert outlets[0]["id"] == str(assigned_outlet_id)
    assert "Brothers Kitchen" in outlets[0]["name"]
    print(f"✅ /api/restaurant/outlets returned exactly 1 scoped outlet: {outlets[0]['name']}")

    # 4. Test GET /api/users - MUST ONLY return The Brothers Kitchen Admin, NOT 12 users!
    users_resp = client.get("/api/users", headers=headers)
    assert users_resp.status_code == 200
    users = users_resp.json()
    assert len(users) == 1, f"Expected 1 user, got {len(users)}"
    assert users[0]["email"] == admin_email
    print(f"✅ /api/users returned exactly 1 scoped user: {users[0]['email']}")

    # 5. Test Unauthenticated Requests - MUST NEVER LEAK DATA
    unauth_shops = client.get("/api/admin/shops")
    assert unauth_shops.status_code == 200
    assert len(unauth_shops.json()) == 0, f"Unauthenticated shops leaked: {unauth_shops.json()}"
    print(f"✅ Unauthenticated /api/admin/shops returned empty list []")

    unauth_outlets = client.get("/api/restaurant/outlets")
    assert unauth_outlets.status_code == 200
    assert len(unauth_outlets.json()) == 0, f"Unauthenticated outlets leaked: {unauth_outlets.json()}"
    print(f"✅ Unauthenticated /api/restaurant/outlets returned empty list []")

    unauth_users = client.get("/api/users")
    assert unauth_users.status_code == 200
    assert len(unauth_users.json()) == 0, f"Unauthenticated users leaked: {unauth_users.json()}"
    print(f"✅ Unauthenticated /api/users returned empty list []")

    unauth_sub = client.get("/api/subscriptions/status")
    assert unauth_sub.status_code == 200
    sub_data = unauth_sub.json()
    assert sub_data["is_active"] is False
    assert sub_data["status"] == "UNPAID"
    assert sub_data["tenant_id"] is None
    print(f"✅ Unauthenticated /api/subscriptions/status safely returned UNPAID without data leak")

    print("\n🎉 ALL MULTI-TENANT ISOLATION TESTS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_new_admin_auto_provisioning_and_isolation()
