import sys
import uuid
from decimal import Decimal
from fastapi.testclient import TestClient

from main import app
from models.database import SessionLocal
from models.user import User
from models.restaurant_outlet import RestaurantOutlet
from dependencies import get_current_user, get_restaurant_staff, get_restaurant_manager

client = TestClient(app)

def run_hardware_tests():
    db = SessionLocal()
    try:
        outlet = db.query(RestaurantOutlet).first()
        user = db.query(User).first()
        if not user or not outlet:
            print("Missing user or outlet. Please ensure base database is populated.")
            return

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_restaurant_staff] = lambda: user
        app.dependency_overrides[get_restaurant_manager] = lambda: user

        print("\n--- 1. Testing Hardware Categories ---")
        res = client.get("/api/hardware/categories")
        assert res.status_code == 200
        categories = res.json()
        print(f"[PASS] Retrieved {len(categories)} categories")

        print("\n--- 2. Testing Hardware Seed Catalog ---")
        res = client.post("/api/hardware/seed")
        assert res.status_code == 200
        print(f"[PASS] Seeded hardware products: {res.json()['message']}")

        print("\n--- 3. Testing Get Hardware Products ---")
        res = client.get("/api/hardware/products")
        assert res.status_code == 200
        products = res.json()
        assert len(products) >= 6
        print(f"[PASS] Retrieved {len(products)} active hardware products")

        # Category filter test
        res = client.get("/api/hardware/products?category=PRINTER")
        assert res.status_code == 200
        printers = res.json()
        assert len(printers) >= 1
        product_id = printers[0]["id"]
        print(f"[PASS] Category filter 'PRINTER' returned {len(printers)} items (Sample: {printers[0]['name']})")

        print("\n--- 4. Testing Get Single Hardware Product Details ---")
        res = client.get(f"/api/hardware/products/{product_id}")
        assert res.status_code == 200
        prod_data = res.json()
        assert prod_data["specifications"] is not None
        assert len(prod_data["features"]) > 0
        print(f"[PASS] Product details verified with specs: {list(prod_data['specifications'].keys())}")

        print("\n--- 5. Testing Create Custom Hardware Product ---")
        test_sku = f"HW-TEST-{uuid.uuid4().hex[:6].upper()}"
        custom_prod = {
            "sku": test_sku,
            "name": "SirfBill Kitchen Display Screen 21.5-inch Industrial",
            "category": "KDS_DISPLAY",
            "brand": "SirfBill",
            "model_number": "SB-KDS21",
            "short_description": "Waterproof stainless steel KDS screen for hot kitchen steam environments.",
            "description": "Full HD 1080p display with anti-glare tempered glass, loud audio alert buzzer, and VESA mount.",
            "specifications": {"screen_size": "21.5 inch", "resolution": "1920x1080", "ip_rating": "IP65 Waterproof front"},
            "features": ["Steam & Grease resistant", "VESA 100x100 wall mount included", "Supports KOT bump bar"],
            "price": 14999.00,
            "mrp": 19999.00,
            "stock_quantity": 20,
            "warranty_months": 24,
            "is_popular": False,
            "is_featured": True
        }
        res = client.post("/api/hardware/products", json=custom_prod)
        assert res.status_code == 201
        custom_id = res.json()["id"]
        print(f"[PASS] Custom hardware product created (ID: {custom_id}, SKU: {test_sku})")

        print("\n--- 6. Testing Patch Hardware Product ---")
        patch_res = client.patch(f"/api/hardware/products/{custom_id}", json={"stock_quantity": 35, "price": 13999.00})
        assert patch_res.status_code == 200
        assert patch_res.json()["stock_quantity"] == 35
        assert Decimal(str(patch_res.json()["price"])) == Decimal("13999.00")
        print("[PASS] Hardware product patched successfully")

        print("\n--- 7. Testing Hardware Purchase Order / Inquiry ---")
        order_payload = {
            "product_id": product_id,
            "outlet_id": str(outlet.id),
            "quantity": 2,
            "contact_name": "Rajesh Kumar",
            "contact_phone": "9876543210",
            "contact_email": "rajesh@restaurant.com",
            "shipping_address": "Shop 4, Park Street, Near Metro Gate 2",
            "city": "Kolkata",
            "state": "West Bengal",
            "pincode": "700016",
            "payment_method": "UPI",
            "notes": "Urgent delivery needed before weekend opening"
        }
        res = client.post("/api/hardware/orders", json=order_payload)
        assert res.status_code == 201
        order_data = res.json()
        order_id = order_data["id"]
        print(f"[PASS] Hardware order placed: {order_data['order_number']}, Total: Rs.{order_data['total_price']}")

        print("\n--- 8. Testing List & Get Hardware Orders ---")
        res = client.get("/api/hardware/orders")
        assert res.status_code == 200
        orders_list = res.json()
        assert len(orders_list) >= 1
        print(f"[PASS] Retrieved {len(orders_list)} hardware orders")

        print("\n--- 9. Testing Update Hardware Order Tracking (Admin) ---")
        order_update = {
            "status": "CONFIRMED",
            "courier_partner": "Blue Dart Express",
            "tracking_number": "BD-884920491"
        }
        res = client.patch(f"/api/hardware/orders/{order_id}", json=order_update)
        assert res.status_code == 200
        assert res.json()["status"] == "CONFIRMED"
        assert res.json()["tracking_number"] == "BD-884920491"
        print("[PASS] Hardware order tracking updated successfully")

        print("\n=======================================================")
        print("ALL HARDWARE MARKETPLACE TESTS PASSED SUCCESSFULLY!")
        print("=======================================================")

    finally:
        db.close()

if __name__ == "__main__":
    run_hardware_tests()
