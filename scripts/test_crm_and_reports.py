import sys
import uuid
from decimal import Decimal
from datetime import date, datetime
from fastapi.testclient import TestClient

from main import app
from models.database import SessionLocal
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from models.restaurant_customer import RestaurantCustomer, RestaurantLoyaltyRules
from dependencies import get_current_user, get_restaurant_staff, get_restaurant_cashier, get_restaurant_manager

client = TestClient(app)

def run_tests():
    db = SessionLocal()
    try:
        # 1. Fetch an outlet and user for testing
        outlet = db.query(RestaurantOutlet).first()
        if not outlet:
            print("No restaurant outlet found in DB. Creating a dummy outlet...")
            outlet = RestaurantOutlet(
                name="Test Dine-in Outlet",
                phone="9999999999",
                tenant_id=uuid.uuid4()
            )
            db.add(outlet)
            db.commit()
            db.refresh(outlet)

        user = db.query(User).first()
        if not user:
            print("No user found in DB. Creating dummy staff...")
            user = User(
                username="test_admin",
                role="ADMIN",
                tenant_id=outlet.tenant_id,
                outlet_id=outlet.id
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Ensure user has outlet_id and tenant_id
        user.outlet_id = outlet.id
        user.tenant_id = outlet.tenant_id
        db.commit()

        # Override auth dependencies
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_restaurant_staff] = lambda: user
        app.dependency_overrides[get_restaurant_cashier] = lambda: user
        app.dependency_overrides[get_restaurant_manager] = lambda: user

        print(f"Testing with Outlet ID: {outlet.id}, Tenant ID: {outlet.tenant_id}")

        # -------------------------------------------------------------
        # MODULE 1: CRM & LOYALTY TESTS
        # -------------------------------------------------------------
        print("\n--- Testing Module 1: CRM Endpoints ---")
        
        # 1. Create Customer
        test_phone = f"98765{uuid.uuid4().hex[:5]}"
        create_payload = {
            "outlet_id": str(outlet.id),
            "name": "Rohan Sharma",
            "phone": test_phone,
            "email": "rohan@example.com",
            "dob": "1992-05-15",
            "anniversary": "2018-11-20",
            "gst_number": "19AAAAA0000A1Z5",
            "preferences": {"dietary": "NON_VEG", "spice": "MEDIUM"},
            "tags": ["NEW"],
            "credit_limit": 5000.00,
            "opt_in_marketing": True,
            "notes": "VIP corporate guest"
        }
        res = client.post("/api/restaurant/crm/customers", json=create_payload)
        assert res.status_code == 201, f"Failed create customer: {res.text}"
        customer_data = res.json()
        customer_id = customer_data["id"]
        print(f"[PASS] Customer created: {customer_data['name']} (ID: {customer_id})")

        # 2. Get Customers (Search & Segment)
        res = client.get(f"/api/restaurant/crm/customers?outlet_id={outlet.id}&search={test_phone}")
        assert res.status_code == 200, f"Failed get customers: {res.text}"
        assert len(res.json()) >= 1
        print(f"[PASS] Search customer by phone returned {len(res.json())} match")

        # 3. Get single Customer
        res = client.get(f"/api/restaurant/crm/customers/{customer_id}")
        assert res.status_code == 200
        print("[PASS] Get single customer profile")

        # 4. Patch Customer
        patch_payload = {"name": "Rohan Sharma (Updated)", "credit_limit": 8000.00}
        res = client.patch(f"/api/restaurant/crm/customers/{customer_id}", json=patch_payload)
        assert res.status_code == 200
        assert res.json()["name"] == "Rohan Sharma (Updated)"
        print("[PASS] Patch customer profile")

        # 5. Customer Insights
        res = client.get(f"/api/restaurant/crm/customers/{customer_id}/insights")
        assert res.status_code == 200
        insights = res.json()
        assert "current_segment" in insights
        assert "top_dishes" in insights
        print(f"[PASS] Customer insights fetched, segment: {insights['current_segment']}")

        # 6. Loyalty Rules (GET & POST)
        res = client.get(f"/api/restaurant/crm/loyalty-rules?outlet_id={outlet.id}")
        assert res.status_code == 200
        print(f"[PASS] Loyalty rules fetched (earn_per_rupees: {res.json()['earn_per_rupees']})")

        rules_payload = {
            "earn_per_rupees": 100.00,
            "point_value_inr": 1.00,
            "min_order_for_redeem": 200.00,
            "max_redeem_pct": 25.00,
            "points_expiry_days": 180,
            "is_active": True
        }
        res = client.post(f"/api/restaurant/crm/loyalty-rules?outlet_id={outlet.id}", json=rules_payload)
        assert res.status_code == 200
        print("[PASS] Loyalty rules configured")

        # 7. Loyalty Adjustment & History
        adjust_payload = {
            "points_delta": 50,
            "reason": "WELCOME_BONUS",
            "idempotency_key": f"BONUS_{uuid.uuid4()}"
        }
        res = client.post(f"/api/restaurant/crm/customers/{customer_id}/loyalty/adjust", json=adjust_payload)
        assert res.status_code == 201
        assert res.json()["balance_after"] == 50
        print("[PASS] Loyalty bonus credited (+50 pts)")

        res = client.get(f"/api/restaurant/crm/customers/{customer_id}/loyalty/history")
        assert res.status_code == 200
        assert len(res.json()) >= 1
        print(f"[PASS] Loyalty history fetched ({len(res.json())} entries)")

        # 8. Khata Statement & Settlement
        res = client.get(f"/api/restaurant/crm/customers/{customer_id}/khata")
        assert res.status_code == 200
        assert "credit_balance" in res.json()
        print("[PASS] Khata statement fetched")

        settle_payload = {
            "amount": 500.00,
            "payment_mode": "UPI",
            "notes": "Settling advance dues",
            "idempotency_key": f"SETTLE_{uuid.uuid4()}"
        }
        res = client.post(f"/api/restaurant/crm/customers/{customer_id}/khata/settle", json=settle_payload)
        assert res.status_code == 201
        print("[PASS] Khata payment settled successfully")

        # 9. Send Notification & History
        notif_payload = {
            "channel": "WHATSAPP",
            "event_type": "PROMOTION",
            "message_body": "Special weekend dinner offer at SirfBill!"
        }
        res = client.post(f"/api/restaurant/crm/customers/{customer_id}/notify", json=notif_payload)
        assert res.status_code == 201
        print("[PASS] Notification logged & dispatched")

        res = client.get(f"/api/restaurant/crm/notifications/history?customer_id={customer_id}")
        assert res.status_code == 200
        assert len(res.json()) >= 1
        print(f"[PASS] Notification history fetched ({len(res.json())} logs)")

        # 10. Run Scheduled Automations
        res = client.post(f"/api/restaurant/crm/scheduled/run-automations?outlet_id={outlet.id}")
        assert res.status_code == 200
        print(f"[PASS] Scheduled automations executed: {res.json()['message']}")

        # -------------------------------------------------------------
        # MODULE 2: EXECUTIVE REPORTS & COSTING TESTS
        # -------------------------------------------------------------
        print("\n--- Testing Module 2: The 5 Executive Reports ---")

        # Report 1: Food Cost Variance
        res = client.get(f"/api/restaurant/reports/food-cost-variance?outlet_id={outlet.id}")
        assert res.status_code == 200, f"Failed Report 1: {res.text}"
        r1 = res.json()
        print(f"[PASS] Report 1 (Food Cost Variance): Sales=Rs.{r1['total_food_sales']}, Theo COGS=Rs.{r1['theoretical_cogs']}, Actual COGS=Rs.{r1['actual_cogs']}")

        # Report 2: Stock Movement
        res = client.get(f"/api/restaurant/reports/stock-movement?outlet_id={outlet.id}")
        assert res.status_code == 200, f"Failed Report 2: {res.text}"
        r2 = res.json()
        print(f"[PASS] Report 2 (Stock Movement): Closing Valuation=Rs.{r2['total_closing_valuation']}, Items tracked={len(r2['items'])}")

        # Report 3: Menu Engineering
        res = client.get(f"/api/restaurant/reports/menu-engineering?outlet_id={outlet.id}")
        assert res.status_code == 200, f"Failed Report 3: {res.text}"
        r3 = res.json()
        print(f"[PASS] Report 3 (Menu Engineering BCG): Items analyzed={r3['total_menu_items_analyzed']}, Stars={r3['stars_count']}, Plowhorses={r3['plowhorses_count']}")

        # Report 4: Procurement Register & Aging
        res = client.get(f"/api/restaurant/reports/procurement?outlet_id={outlet.id}")
        assert res.status_code == 200, f"Failed Report 4: {res.text}"
        r4 = res.json()
        print(f"[PASS] Report 4 (Procurement & GST): Purchase Spend=Rs.{r4['total_purchase_spend']}, Input GST=Rs.{r4['total_input_gst_paid']}, Aging Buckets={len(r4['aging_buckets'])}")

        # Report 5: Shrinkage & Wastage Breakdown
        res = client.get(f"/api/restaurant/reports/shrinkage?outlet_id={outlet.id}")
        assert res.status_code == 200, f"Failed Report 5: {res.text}"
        r5 = res.json()
        print(f"[PASS] Report 5 (Shrinkage & Wastage): Total Loss=Rs.{r5['total_shrinkage_rupees']}, Spoilage=Rs.{r5['spoilage_total']}, Burnt/Ruined=Rs.{r5['burnt_ruined_total']}")

        print("\n=======================================================")
        print("ALL TESTS PASSED! MODULE 1 AND MODULE 2 BACKEND COMPLETE")
        print("=======================================================")

    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
