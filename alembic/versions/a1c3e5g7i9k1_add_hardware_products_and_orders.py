"""add_hardware_products_and_orders

Revision ID: a1c3e5g7i9k1
Revises: f2d4b6a8c0e2
Create Date: 2026-11-21 08:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3e5g7i9k1'
down_revision: Union[str, Sequence[str], None] = 'f2d4b6a8c0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create hardware_products table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS hardware_products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sku VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL,
            category VARCHAR(50) NOT NULL,
            brand VARCHAR(100) NOT NULL DEFAULT 'SirfBill',
            model_number VARCHAR(100),
            short_description TEXT,
            description TEXT,
            specifications JSON NOT NULL DEFAULT '{}'::json,
            features JSON NOT NULL DEFAULT '[]'::json,
            price NUMERIC(10, 2) NOT NULL,
            mrp NUMERIC(10, 2),
            discount_pct NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
            tax_rate NUMERIC(5, 2) NOT NULL DEFAULT 18.00,
            primary_image_url TEXT,
            images JSON NOT NULL DEFAULT '[]'::json,
            stock_quantity INTEGER NOT NULL DEFAULT 50,
            in_stock BOOLEAN NOT NULL DEFAULT true,
            warranty_months INTEGER NOT NULL DEFAULT 12,
            is_popular BOOLEAN NOT NULL DEFAULT false,
            is_featured BOOLEAN NOT NULL DEFAULT false,
            is_active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_hardware_products_sku ON hardware_products (sku);
        CREATE INDEX IF NOT EXISTS idx_hardware_products_name ON hardware_products (name);
        CREATE INDEX IF NOT EXISTS idx_hardware_products_category ON hardware_products (category);
    """))

    # 2. Create hardware_orders table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS hardware_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE SET NULL,
            product_id UUID NOT NULL REFERENCES hardware_products(id) ON DELETE RESTRICT,
            order_number VARCHAR(50) UNIQUE NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price NUMERIC(10, 2) NOT NULL,
            total_price NUMERIC(10, 2) NOT NULL,
            contact_name VARCHAR(150) NOT NULL,
            contact_phone VARCHAR(30) NOT NULL,
            contact_email VARCHAR(120),
            shipping_address TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            pincode VARCHAR(20),
            status VARCHAR(30) NOT NULL DEFAULT 'NEW',
            payment_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
            payment_method VARCHAR(50) DEFAULT 'UPI',
            payment_reference VARCHAR(100),
            tracking_number VARCHAR(100),
            courier_partner VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_hardware_orders_tenant ON hardware_orders (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_hardware_orders_outlet ON hardware_orders (outlet_id);
        CREATE INDEX IF NOT EXISTS idx_hardware_orders_product ON hardware_orders (product_id);
        CREATE INDEX IF NOT EXISTS idx_hardware_orders_status ON hardware_orders (status);
        CREATE INDEX IF NOT EXISTS idx_hardware_orders_number ON hardware_orders (order_number);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS hardware_orders CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS hardware_products CASCADE;"))
