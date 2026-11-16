"""upgrade_procurement_and_inventory_schema

Revision ID: f1a3b5c7d9e0
Revises: d9f2b8c0e413
Create Date: 2026-11-16 18:46:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a3b5c7d9e0'
down_revision: Union[str, Sequence[str], None] = 'd9f2b8c0e413'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Complete Restaurant Ingredients Master Fields (Dual-UOM, Par Levels, Costing, Storage)
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

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_primary_supplier ON restaurant_ingredients (primary_supplier_id);"))

    # 2. Goods Received Note (GRN) Document Scan / Attachment URL
    conn.execute(sa.text("ALTER TABLE restaurant_grn ADD COLUMN IF NOT EXISTS invoice_document_url VARCHAR(500);"))

    # 3. Dock Rejection & Food Safety Audit Columns on GRN Items
    conn.execute(sa.text("ALTER TABLE restaurant_grn_items ADD COLUMN IF NOT EXISTS quantity_rejected NUMERIC(12, 3) DEFAULT 0.000;"))
    conn.execute(sa.text("ALTER TABLE restaurant_grn_items ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR(255);"))

    # 4. Populate restaurant_suppliers from existing distributors table for instant onboarding
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
        WHERE d.name IS NOT NULL
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            phone = EXCLUDED.phone,
            gstin = EXCLUDED.gstin,
            contact_person = EXCLUDED.contact_person,
            is_active = TRUE;
    """))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TABLE restaurant_grn_items DROP COLUMN IF EXISTS rejection_reason;"))
    conn.execute(sa.text("ALTER TABLE restaurant_grn_items DROP COLUMN IF EXISTS quantity_rejected;"))
    conn.execute(sa.text("ALTER TABLE restaurant_grn DROP COLUMN IF EXISTS invoice_document_url;"))

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ingredients_primary_supplier;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS image_url;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS last_restocked_at;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS shelf_life_days;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS is_perishable;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS primary_supplier_id;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS cost_per_purchase_unit;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS ideal_par_level;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS min_par_level;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS uom_conversion_factor;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS recipe_uom;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS purchase_uom;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS storage_location;"))
