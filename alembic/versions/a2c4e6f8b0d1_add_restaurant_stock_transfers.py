"""add_restaurant_stock_transfers

Revision ID: a2c4e6f8b0d1
Revises: f1a3b5c7d9e0
Create Date: 2026-11-17 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d1'
down_revision: Union[str, Sequence[str], None] = 'f1a3b5c7d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create restaurant_stock_transfers table
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

    # Composite unique index to avoid cross-tenant collisions on transfer numbers
    conn.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_transfers_tenant_number 
        ON restaurant_stock_transfers (tenant_id, transfer_number);
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfers_status 
        ON restaurant_stock_transfers (tenant_id, status);
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfers_from_outlet 
        ON restaurant_stock_transfers (from_outlet_id);
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfers_to_outlet 
        ON restaurant_stock_transfers (to_outlet_id);
    """))

    # 2. Create restaurant_stock_transfer_items table
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

    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_transfer 
        ON restaurant_stock_transfer_items (transfer_id);
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_ing 
        ON restaurant_stock_transfer_items (ingredient_id);
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_dest_ing 
        ON restaurant_stock_transfer_items (destination_ingredient_id);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_stock_transfer_items CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_stock_transfers CASCADE;"))
