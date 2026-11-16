"""add_restaurant_procurement_tables

Revision ID: d9f2b8c0e413
Revises: c8e1a7b9f302
Create Date: 2026-11-16 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f2b8c0e413'
down_revision: Union[str, Sequence[str], None] = 'c8e1a7b9f302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Suppliers
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

    # 2. Purchase Orders
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

    # 3. Purchase Order Items
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

    # 4. GRN
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
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_outlet ON restaurant_grn (outlet_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_po ON restaurant_grn (po_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_supplier ON restaurant_grn (supplier_id);"))

    # 5. GRN Items
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
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_items_grn ON restaurant_grn_items (grn_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_grn_items_ingredient ON restaurant_grn_items (ingredient_id);"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_grn_items CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_grn CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_purchase_order_items CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_purchase_orders CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_suppliers CASCADE;"))
