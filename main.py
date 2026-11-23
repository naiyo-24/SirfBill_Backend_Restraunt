from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from fastapi.staticfiles import StaticFiles
import os

# Create root uploads directories
# os.makedirs("uploads/reports", exist_ok=True)
# os.makedirs("uploads/profiles", exist_ok=True)
# os.makedirs("uploads/prescriptions", exist_ok=True)
# os.makedirs("uploads/banners", exist_ok=True)
# os.makedirs("uploads/doctors", exist_ok=True)
# os.makedirs("uploads/stories", exist_ok=True)

# Import models to ensure they are registered with SQLAlchemy
from models import Base, engine
# from graphql_api.schema import schema

import sqlalchemy as sa


# Create the tables automatically first time
Base.metadata.create_all(bind=engine)

# Auto-apply essential schema columns & performance indexes on startup
try:
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS account_holder_name VARCHAR;"))
        # Enable pg_trgm for high-speed sub-millisecond full-text and pattern search
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        
        # High-performance GIN Trigram indexes on millions of rows
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_menu_items_name_trgm ON restaurant_menu_items USING gin (name gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_menu_items_shortcode_trgm ON restaurant_menu_items USING gin (short_code gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_menu_items_outlet_active ON restaurant_menu_items (outlet_id, is_active);"))

        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_customers_name_trgm ON restaurant_customers USING gin (name gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_customers_phone_trgm ON restaurant_customers USING gin (phone gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_customers_outlet_active ON restaurant_customers (outlet_id, is_active);"))

        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_orders_outlet_status ON restaurant_orders (outlet_id, status);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_orders_customer_phone ON restaurant_orders (customer_phone);"))

        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_users_name_trgm ON users USING gin (name gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_users_phone_trgm ON users USING gin (phone gin_trgm_ops);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_users_tenant_role ON users (tenant_id, role);"))

        # Inventory & Ingredient Categories schema assurance
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_ingredient_categories (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(50),
                storage_zone_temp VARCHAR(150),
                color_code VARCHAR(30),
                icon VARCHAR(50),
                description TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES restaurant_ingredient_categories(id) ON DELETE SET NULL;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS storage_zone VARCHAR(100);"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS storage_location VARCHAR(100);"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS purchase_uom VARCHAR(20) DEFAULT 'KG';"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS recipe_uom VARCHAR(20) DEFAULT 'G';"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS uom_conversion_factor NUMERIC(12, 4) DEFAULT 1.0000;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS min_par_level NUMERIC(12, 3) DEFAULT 0.000;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS ideal_par_level NUMERIC(12, 3) DEFAULT 0.000;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS cost_per_purchase_unit NUMERIC(10, 2) DEFAULT 0.00;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS primary_supplier_id UUID REFERENCES distributors(id) ON DELETE SET NULL;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS is_perishable BOOLEAN DEFAULT FALSE;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER;"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS last_restocked_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();"))
        conn.execute(sa.text("ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS image_url TEXT;"))
        
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ing_cat_outlet ON restaurant_ingredient_categories (outlet_id, is_active);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ing_cat_tenant ON restaurant_ingredient_categories (tenant_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_cat ON restaurant_ingredients (category_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_outlet_active ON restaurant_ingredients (outlet_id, is_active);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_tenant ON restaurant_ingredients (tenant_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_primary_supplier ON restaurant_ingredients (primary_supplier_id);"))

        # Procurement & Purchase Order tables schema assurance
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_suppliers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                name VARCHAR(150) NOT NULL,
                code VARCHAR(50),
                contact_person VARCHAR(100),
                phone VARCHAR(30),
                email VARCHAR(120),
                address TEXT,
                gstin VARCHAR(50),
                fssai VARCHAR(50),
                payment_terms VARCHAR(50) DEFAULT 'NET_15',
                bank_details JSON DEFAULT '{}'::json,
                notes TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_suppliers_outlet ON restaurant_suppliers (outlet_id, is_active);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON restaurant_suppliers (tenant_id);"))

        conn.execute(sa.text("""
            INSERT INTO restaurant_suppliers (id, outlet_id, tenant_id, name, code, contact_person, phone, gstin, is_active, created_at, updated_at)
            SELECT 
                d.id, 
                COALESCE(d.shop_id, (SELECT id FROM restaurant_outlets LIMIT 1)), 
                COALESCE(d.tenant_id, (SELECT tenant_id FROM restaurant_outlets LIMIT 1)),
                d.name, 
                'SUP-' || SUBSTRING(UPPER(REGEXP_REPLACE(d.name, '[^a-zA-Z0-9]', '', 'g')) FROM 1 FOR 6),
                d.contact_person, 
                d.phone, 
                d.gstin, 
                TRUE,
                COALESCE(d.created_at, NOW()), 
                NOW()
            FROM distributors d
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                phone = EXCLUDED.phone,
                gstin = EXCLUDED.gstin,
                contact_person = EXCLUDED.contact_person,
                is_active = TRUE;
        """))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_purchase_orders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                supplier_id UUID NOT NULL REFERENCES restaurant_suppliers(id) ON DELETE RESTRICT,
                po_number VARCHAR(50) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
                order_date DATE NOT NULL DEFAULT CURRENT_DATE,
                expected_delivery_date DATE,
                subtotal NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                tax_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                delivery_address TEXT,
                notes TEXT,
                created_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                approved_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_po_outlet_status ON restaurant_purchase_orders (outlet_id, status);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_po_tenant ON restaurant_purchase_orders (tenant_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_po_supplier ON restaurant_purchase_orders (supplier_id);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_purchase_order_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                po_id UUID NOT NULL REFERENCES restaurant_purchase_orders(id) ON DELETE CASCADE,
                ingredient_id UUID NOT NULL REFERENCES restaurant_ingredients(id) ON DELETE RESTRICT,
                quantity_ordered NUMERIC(12, 3) NOT NULL,
                quantity_received NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                unit VARCHAR(20) NOT NULL,
                unit_price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                tax_rate NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
                tax_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                total_price NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                notes VARCHAR(255)
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_po_items_po ON restaurant_purchase_order_items (po_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_po_items_ingredient ON restaurant_purchase_order_items (ingredient_id);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_grn (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                po_id UUID REFERENCES restaurant_purchase_orders(id) ON DELETE SET NULL,
                supplier_id UUID NOT NULL REFERENCES restaurant_suppliers(id) ON DELETE RESTRICT,
                grn_number VARCHAR(50) NOT NULL,
                supplier_invoice_no VARCHAR(100),
                invoice_date DATE,
                received_date TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                received_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                payment_status VARCHAR(30) NOT NULL DEFAULT 'UNPAID',
                remarks TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("ALTER TABLE restaurant_grn ADD COLUMN IF NOT EXISTS invoice_document_url VARCHAR(500);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_outlet ON restaurant_grn (outlet_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_po ON restaurant_grn (po_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_supplier ON restaurant_grn (supplier_id);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_grn_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                grn_id UUID NOT NULL REFERENCES restaurant_grn(id) ON DELETE CASCADE,
                ingredient_id UUID NOT NULL REFERENCES restaurant_ingredients(id) ON DELETE RESTRICT,
                po_item_id UUID REFERENCES restaurant_purchase_order_items(id) ON DELETE SET NULL,
                quantity_received NUMERIC(12, 3) NOT NULL,
                quantity_rejected NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                rejection_reason VARCHAR(255),
                unit VARCHAR(20) NOT NULL,
                unit_price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                tax_rate NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
                tax_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                total_price NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                batch_number VARCHAR(50),
                expiry_date DATE
            );
        """))
        conn.execute(sa.text("ALTER TABLE restaurant_grn_items ADD COLUMN IF NOT EXISTS quantity_rejected NUMERIC(12, 3) DEFAULT 0.000;"))
        conn.execute(sa.text("ALTER TABLE restaurant_grn_items ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(255);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_items_grn ON restaurant_grn_items (grn_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_items_ingredient ON restaurant_grn_items (ingredient_id);"))

        # Stock Ledger Cost Snapshots & Immutability Trigger
        conn.execute(sa.text("ALTER TABLE restaurant_stock_ledger ADD COLUMN IF NOT EXISTS unit_cost_at_time NUMERIC(12, 4) DEFAULT 0.0000;"))
        conn.execute(sa.text("ALTER TABLE restaurant_stock_ledger ADD COLUMN IF NOT EXISTS total_cost NUMERIC(12, 2) DEFAULT 0.00;"))
        conn.execute(sa.text("ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS allow_negative_stock BOOLEAN DEFAULT TRUE;"))

        conn.execute(sa.text("""
            CREATE OR REPLACE FUNCTION trg_prevent_stock_ledger_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'restaurant_stock_ledger is append-only. Updates and deletions are strictly forbidden. Use REVERSAL transactions instead.';
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_stock_ledger_immutable'
                ) THEN
                    CREATE TRIGGER trg_stock_ledger_immutable
                    BEFORE UPDATE OR DELETE ON restaurant_stock_ledger
                    FOR EACH ROW EXECUTE FUNCTION trg_prevent_stock_ledger_mutation();
                END IF;
            END $$;
        """))

        # Stock Transfer tables schema assurance
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_stock_transfers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                transfer_number VARCHAR(50) NOT NULL,
                transfer_type VARCHAR(30) NOT NULL DEFAULT 'INTER_BRANCH',
                from_outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                to_outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                from_station VARCHAR(100),
                to_station VARCHAR(100),
                status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
                initiated_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                dispatched_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                received_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                dispatched_at TIMESTAMP WITHOUT TIME ZONE,
                received_at TIMESTAMP WITHOUT TIME ZONE,
                vehicle_number VARCHAR(50),
                driver_name VARCHAR(100),
                driver_phone VARCHAR(50),
                total_items INTEGER NOT NULL DEFAULT 0,
                total_valuation NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                notes TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_transfers_tenant_number ON restaurant_stock_transfers (tenant_id, transfer_number);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfers_status ON restaurant_stock_transfers (tenant_id, status);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfers_from_outlet ON restaurant_stock_transfers (from_outlet_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfers_to_outlet ON restaurant_stock_transfers (to_outlet_id);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_stock_transfer_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                transfer_id UUID NOT NULL REFERENCES restaurant_stock_transfers(id) ON DELETE CASCADE,
                ingredient_id UUID NOT NULL REFERENCES restaurant_ingredients(id) ON DELETE RESTRICT,
                destination_ingredient_id UUID REFERENCES restaurant_ingredients(id) ON DELETE SET NULL,
                ingredient_name VARCHAR(150) NOT NULL,
                sku VARCHAR(50),
                unit VARCHAR(20) NOT NULL,
                quantity_requested NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                quantity_dispatched NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                quantity_received NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                quantity_variance NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                unit_cost NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
                total_cost NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                variance_reason VARCHAR(255),
                batch_number VARCHAR(100),
                expiry_date TIMESTAMP WITHOUT TIME ZONE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_transfer ON restaurant_stock_transfer_items (transfer_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_ing ON restaurant_stock_transfer_items (ingredient_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_dest_ing ON restaurant_stock_transfer_items (destination_ingredient_id);"))

        # Restaurant Recipes (BOM) schema assurance
        conn.execute(sa.text("ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE CASCADE;"))
        conn.execute(sa.text("ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS modifier_option_id UUID REFERENCES restaurant_modifier_options(id) ON DELETE CASCADE;"))
        conn.execute(sa.text("ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS produced_ingredient_id UUID REFERENCES restaurant_ingredients(id) ON DELETE SET NULL;"))
        conn.execute(sa.text("ALTER TABLE restaurant_recipes ALTER COLUMN item_id DROP NOT NULL;"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_recipes_outlet ON restaurant_recipes (outlet_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_recipes_modifier ON restaurant_recipes (modifier_option_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_recipes_produced_ing ON restaurant_recipes (produced_ingredient_id);"))

        # Physical Stock Audits schema assurance
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_stock_audits (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                batch_code VARCHAR(100) UNIQUE NOT NULL,
                outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                auditor_id UUID REFERENCES users(id) ON DELETE SET NULL,
                audit_date DATE NOT NULL DEFAULT CURRENT_DATE,
                audit_started_at TIMESTAMP WITHOUT TIME ZONE,
                notes TEXT,
                total_items_audited INTEGER NOT NULL DEFAULT 0,
                items_adjusted INTEGER NOT NULL DEFAULT 0,
                total_surplus_rupees NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                total_deficit_rupees NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                net_variance_rupees NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_audits_outlet ON restaurant_stock_audits (outlet_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_audits_batch ON restaurant_stock_audits (batch_code);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS restaurant_stock_audit_items (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                audit_id UUID NOT NULL REFERENCES restaurant_stock_audits(id) ON DELETE CASCADE,
                ingredient_id UUID NOT NULL REFERENCES restaurant_ingredients(id) ON DELETE CASCADE,
                ingredient_name VARCHAR(150),
                recipe_uom VARCHAR(20) NOT NULL,
                purchase_uom VARCHAR(20),
                input_uom VARCHAR(20) DEFAULT 'RECIPE',
                previous_stock NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                expected_stock NUMERIC(12, 3),
                physical_count NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                raw_input_count NUMERIC(12, 3),
                variance NUMERIC(12, 3) NOT NULL DEFAULT 0.000,
                unit_cost_at_time NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
                variance_rupees NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
                status VARCHAR(20) NOT NULL DEFAULT 'MATCHED',
                notes TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_audit_items_audit ON restaurant_stock_audit_items (audit_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_stock_audit_items_ing ON restaurant_stock_audit_items (ingredient_id);"))

        # Subscription System schema assurance
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plan_code VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                price NUMERIC(10, 2) NOT NULL DEFAULT 299.00,
                currency VARCHAR(10) NOT NULL DEFAULT 'INR',
                billing_cycle VARCHAR(20) NOT NULL DEFAULT 'MONTHLY',
                duration_days INTEGER NOT NULL DEFAULT 30,
                features JSON NOT NULL DEFAULT '[]'::json,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                is_popular BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("ALTER TABLE subscription_plans ALTER COLUMN id SET DEFAULT gen_random_uuid();"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_sub_plans_code ON subscription_plans (plan_code);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS tenant_subscriptions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE SET NULL,
                plan_id UUID NOT NULL REFERENCES subscription_plans(id) ON DELETE RESTRICT,
                status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
                price_paid NUMERIC(10, 2) NOT NULL DEFAULT 299.00,
                currency VARCHAR(10) NOT NULL DEFAULT 'INR',
                started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                payment_method VARCHAR(50) DEFAULT 'UPI',
                payment_reference VARCHAR(100),
                invoice_number VARCHAR(100),
                notes TEXT,
                auto_renew BOOLEAN NOT NULL DEFAULT TRUE,
                purchased_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(sa.text("ALTER TABLE tenant_subscriptions ALTER COLUMN id SET DEFAULT gen_random_uuid();"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_tenant_sub_tenant ON tenant_subscriptions (tenant_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_tenant_sub_status ON tenant_subscriptions (status);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_tenant_sub_expires ON tenant_subscriptions (expires_at);"))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS subscription_payments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subscription_id UUID NOT NULL REFERENCES tenant_subscriptions(id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                currency VARCHAR(10) NOT NULL DEFAULT 'INR',
                payment_gateway VARCHAR(50) NOT NULL DEFAULT 'MANUAL_UPI',
                gateway_order_id VARCHAR(100),
                gateway_payment_id VARCHAR(100),
                status VARCHAR(30) NOT NULL DEFAULT 'SUCCESS',
                payment_date TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                notes TEXT
            );
        """))
        conn.execute(sa.text("ALTER TABLE subscription_payments ALTER COLUMN id SET DEFAULT gen_random_uuid();"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_sub_payments_sub ON subscription_payments (subscription_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_sub_payments_tenant ON subscription_payments (tenant_id);"))

        # Seed the ₹299/month default plan if not present
        conn.execute(sa.text("""
            INSERT INTO subscription_plans (
                id, plan_code, name, description, price, currency, billing_cycle, duration_days, features, is_active, is_popular, created_at, updated_at
            ) VALUES (
                gen_random_uuid(),
                'RESTAURANT_PRO_299',
                'SirfBill Restaurant Pro',
                'Complete all-in-one restaurant management platform for point-of-sale, recipe costing, kitchen display, and perpetual inventory.',
                299.00,
                'INR',
                'MONTHLY',
                30,
                '["Fast Touch POS Billing & Multi-Station KOT Printing", "Complete Recipe Management & Automatic BOM Inventory Deductions", "Multi-Branch Real-Time Inventory & Stock Transfers", "Physical Stock Audit & Variance Reconciliation", "Wastage & Spoilage Loss Tracking with Rupee Costing", "Interactive Table Layout & Live Kitchen Display (KDS)", "Automated Purchase Orders & Vendor GRN Inwarding", "Role-Based Multi-Staff Logins & Daily Shift Closure Reports"]'::json,
                TRUE,
                TRUE,
                NOW(),
                NOW()
            )
            ON CONFLICT (plan_code) DO NOTHING;
        """))
except Exception as e:
    print(f"Schema startup migration note: {e}")

# Legacy schema migrations note: Handled via Alembic in production
# try:
#     with engine.begin() as conn:
#         conn.execute(sa.text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS cin_number VARCHAR;"))
#         conn.execute(sa.text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS upi_id VARCHAR;"))
#         conn.execute(sa.text("ALTER TABLE inventory_items ALTER COLUMN expiry_date DROP NOT NULL;"))
# except Exception as e:
#     print(f"Schema migration note: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup before app starts (like connecting to DB, handled by sqlalchemy sync here)
    yield
    # Cleanup when app stops

app = FastAPI(title="SirfBill Restaurant Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5194", "http://192.168.0.222:5194", "https://sirfapi.vwings247.me", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static files directory
os.makedirs("uploads", exist_ok=True)
os.makedirs("uploads/inventory", exist_ok=True)
os.makedirs("uploads/shop", exist_ok=True)
os.makedirs("uploads/kots", exist_ok=True)
os.makedirs("uploads/bills", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

os.makedirs("downloads", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="downloads"), name="downloads")

from routes.user import router as user_router, admin_router as user_admin_router
# from routes.doctor import router as doctor_router
# from routes.appointment import router as appointment_router
# from routes.lab_catalog import router as lab_catalog_router
# from routes.lab_booking import router as lab_booking_router
# from routes.story import router as story_router
from routes.auth import router as auth_router, alias_router as auth_alias_router
# Legacy payment, pos, accounts, and purchase routers retired for consolidated Restaurant platform
# from routes.payment import router as payment_router
# from routes.dashboard import router as dashboard_router
# from routes.banner import router as banner_router
# from routes.settings import router as settings_router
from routes.shop_admin import router as shop_admin_router
from routes.shop_settings import router as shop_settings_router
# from routes.pos_admin import router as pos_admin_router
# from routes.documents_admin import router as documents_admin_router
# from routes.search import router as search_router
# from routes.shop_orders import router as shop_orders_router
# from routes.accounts import router as accounts_router
# from routes.transactions import router as transactions_router
# from routes.transaction_categories import router as transaction_categories_router
# from routes.accounting_extended import router as accounting_extended_router
# from routes.lab_category import router as lab_category_router
# from routes.lab_template import router as lab_template_router
from routes.distributor_admin import router as distributor_admin_router
# from routes.purchase_admin import router as purchase_admin_router

# Mount GraphQL Endpoint (Commented out for clean restaurant backend)
# graphql_app = GraphQLRouter(schema)
# app.include_router(graphql_app, prefix="/graphql")


# Mount REST Routes
app.include_router(user_router)
app.include_router(user_admin_router)
# app.include_router(doctor_router)
# app.include_router(appointment_router)
# app.include_router(lab_catalog_router)
# app.include_router(lab_booking_router)
# app.include_router(story_router)
app.include_router(auth_router)
app.include_router(auth_alias_router)
# app.include_router(payment_router)
# app.include_router(dashboard_router)
# app.include_router(banner_router)

# app.include_router(settings_router)
app.include_router(shop_admin_router)
from routes.shop_admin import alias_router as shop_alias_router
app.include_router(shop_alias_router)
app.include_router(shop_settings_router)
# app.include_router(pos_admin_router)
# app.include_router(documents_admin_router)
# app.include_router(search_router)
# app.include_router(shop_orders_router)
# app.include_router(accounts_router)
# app.include_router(transactions_router)
# app.include_router(transaction_categories_router)
# app.include_router(accounting_extended_router)
# app.include_router(lab_category_router)
# app.include_router(lab_template_router)
app.include_router(distributor_admin_router)
# app.include_router(purchase_admin_router)

# Printer Shop Routes (Commented out for Restaurant Backend)
# from routes.print_services import router as print_services_router
# from routes.print_jobs import router as print_jobs_router
# from routes.machines import router as machines_router
from routes.app_version import router as app_version_router

# app.include_router(print_services_router)
# app.include_router(print_jobs_router)
# app.include_router(machines_router)
app.include_router(app_version_router)

# --- Restaurant Domain Routers ---
from routes.restaurant_outlets import router as restaurant_outlets_router
from routes.restaurant_menu import router as restaurant_menu_router
from routes.restaurant_tables import router as restaurant_tables_router
from routes.restaurant_orders import router as restaurant_orders_router
from routes.restaurant_kitchen import router as restaurant_kitchen_router
from routes.restaurant_tenders import router as restaurant_tenders_router
from routes.restaurant_shifts import router as restaurant_shifts_router
from routes.restaurant_reports import router as restaurant_reports_router
from routes.restaurant_inventory import router as restaurant_inventory_router
from routes.restaurant_stock_transfer import router as restaurant_stock_transfer_router
from routes.restaurant_crm import router as restaurant_crm_router
from routes.restaurant_procurement import router as restaurant_procurement_router
from routes.restaurant_subscriptions import router as restaurant_subscriptions_router
from routes.hardware_products import router as hardware_router

app.include_router(restaurant_outlets_router)
app.include_router(restaurant_menu_router)
app.include_router(restaurant_tables_router)
app.include_router(restaurant_orders_router)
app.include_router(restaurant_kitchen_router)
app.include_router(restaurant_tenders_router)
app.include_router(restaurant_shifts_router)
app.include_router(restaurant_reports_router)
app.include_router(restaurant_inventory_router)
app.include_router(restaurant_stock_transfer_router)
app.include_router(restaurant_crm_router)
app.include_router(restaurant_procurement_router)
app.include_router(restaurant_subscriptions_router)
app.include_router(hardware_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to SirfBill Restaurant Backend"}


