"""consolidate_and_join_database_tables

Revision ID: b2d4f6h8j0l2
Revises: a1c3e5g7i9k1
Create Date: 2026-11-21 11:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2d4f6h8j0l2'
down_revision: Union[str, Sequence[str], None] = 'a1c3e5g7i9k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # 1. CONSOLIDATION: restaurant_item_prices -> restaurant_menu_items
    # =========================================================================
    conn.execute(sa.text("""
        ALTER TABLE restaurant_menu_items 
        ADD COLUMN IF NOT EXISTS takeaway_price NUMERIC(10, 2),
        ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(10, 2),
        ADD COLUMN IF NOT EXISTS variant_prices JSONB DEFAULT '[]'::jsonb;
    """))

    conn.execute(sa.text("""
        UPDATE restaurant_menu_items m
        SET price = COALESCE(p.price, m.price, 0.00)
        FROM restaurant_item_prices p
        WHERE m.id = p.item_id AND (p.channel = 'DEFAULT' OR p.channel IS NULL);
    """))

    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_item_prices CASCADE;"))

    # =========================================================================
    # 2. CONSOLIDATION: restaurant_modifier_options -> restaurant_modifier_groups
    # =========================================================================
    conn.execute(sa.text("""
        ALTER TABLE restaurant_modifier_groups
        ADD COLUMN IF NOT EXISTS options JSONB DEFAULT '[]'::jsonb,
        ADD COLUMN IF NOT EXISTS applicable_item_ids JSONB DEFAULT '[]'::jsonb;
    """))

    conn.execute(sa.text("""
        ALTER TABLE restaurant_recipes 
        DROP CONSTRAINT IF EXISTS restaurant_recipes_modifier_option_id_fkey;
    """))

    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_item_modifier_groups CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_modifier_options CASCADE;"))

    # =========================================================================
    # 3. CONSOLIDATION: restaurant_recipe_lines -> restaurant_recipes
    # =========================================================================
    conn.execute(sa.text("""
        ALTER TABLE restaurant_recipes
        ADD COLUMN IF NOT EXISTS items JSONB DEFAULT '[]'::jsonb;
    """))

    conn.execute(sa.text("""
        UPDATE restaurant_recipes r
        SET items = (
            SELECT COALESCE(json_agg(json_build_object(
                'ingredient_id', l.ingredient_id,
                'quantity_required', l.quantity_required,
                'unit', l.unit
            )), '[]'::json)
            FROM restaurant_recipe_lines l
            WHERE l.recipe_id = r.id
        );
    """))

    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_recipe_lines CASCADE;"))

    # =========================================================================
    # 4. CONSOLIDATION: Loyalty + Credit Ledgers -> restaurant_customer_ledger
    # =========================================================================
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS restaurant_customer_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
            customer_id UUID REFERENCES restaurant_customers(id) ON DELETE CASCADE,
            order_id UUID REFERENCES restaurant_orders(id) ON DELETE SET NULL,
            tenant_id UUID,
            ledger_type VARCHAR(30) NOT NULL,
            transaction_type VARCHAR(30) NOT NULL,
            points_delta INTEGER DEFAULT 0 NOT NULL,
            amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
            balance_after NUMERIC(12, 2) NOT NULL,
            payment_mode VARCHAR(50),
            reason VARCHAR(100),
            notes TEXT,
            idempotency_key VARCHAR(100),
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() AT TIME ZONE 'utc') NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_restaurant_customer_ledger_customer_id ON restaurant_customer_ledger(customer_id);
        CREATE INDEX IF NOT EXISTS ix_restaurant_customer_ledger_outlet_id ON restaurant_customer_ledger(outlet_id);
        CREATE INDEX IF NOT EXISTS ix_restaurant_customer_ledger_order_id ON restaurant_customer_ledger(order_id);
    """))

    conn.execute(sa.text("""
        INSERT INTO restaurant_customer_ledger (
            id, customer_id, outlet_id, tenant_id, order_id, ledger_type, transaction_type,
            points_delta, amount, balance_after, reason, idempotency_key, created_at
        )
        SELECT 
            l.id, l.customer_id, c.outlet_id, c.tenant_id, l.source_order_id, 'LOYALTY', l.reason,
            l.points_delta, 0.00, l.balance_after, l.reason, l.idempotency_key, l.created_at
        FROM restaurant_loyalty_ledger l
        JOIN restaurant_customers c ON l.customer_id = c.id
        ON CONFLICT (id) DO NOTHING;
    """))

    conn.execute(sa.text("""
        INSERT INTO restaurant_customer_ledger (
            id, customer_id, outlet_id, tenant_id, order_id, ledger_type, transaction_type,
            points_delta, amount, balance_after, payment_mode, notes, idempotency_key, created_at
        )
        SELECT 
            cl.id, cl.customer_id, cl.outlet_id, cl.tenant_id, cl.order_id, 'CREDIT', cl.transaction_type,
            0, cl.amount, cl.balance_after, cl.payment_mode, cl.notes, cl.idempotency_key, cl.created_at
        FROM restaurant_customer_credit_ledger cl
        ON CONFLICT (id) DO NOTHING;
    """))

    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_loyalty_ledger CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_customer_credit_ledger CASCADE;"))

    # =========================================================================
    # 5. CLEANUP: Foreign Keys & Obsolete 0-row Legacy Retail Tables
    # =========================================================================
    conn.execute(sa.text("""
        ALTER TABLE restaurant_outlets 
        DROP CONSTRAINT IF EXISTS restaurant_outlets_shop_id_fkey;
    """))

    conn.execute(sa.text("""
        ALTER TABLE restaurant_ingredients 
        DROP CONSTRAINT IF EXISTS restaurant_ingredients_primary_supplier_id_fkey;
    """))

    conn.execute(sa.text("""
        ALTER TABLE restaurant_ingredients 
        ADD CONSTRAINT restaurant_ingredients_primary_supplier_id_fkey 
        FOREIGN KEY (primary_supplier_id) REFERENCES restaurant_suppliers(id) ON DELETE SET NULL;
    """))

    conn.execute(sa.text("""
        DROP TABLE IF EXISTS shop_bill_items CASCADE;
        DROP TABLE IF EXISTS shop_bills CASCADE;
        DROP TABLE IF EXISTS purchase_bill_items CASCADE;
        DROP TABLE IF EXISTS purchase_bills CASCADE;
        DROP TABLE IF EXISTS inventory_items CASCADE;
        DROP TABLE IF EXISTS racks CASCADE;
        DROP TABLE IF EXISTS categories CASCADE;
        DROP TABLE IF EXISTS transactions CASCADE;
        DROP TABLE IF EXISTS transaction_categories CASCADE;
        DROP TABLE IF EXISTS accounts CASCADE;
        DROP TABLE IF EXISTS payments CASCADE;
        DROP TABLE IF EXISTS otp_codes CASCADE;
    """))


def downgrade() -> None:
    # Minimal downgrade placeholder
    pass
