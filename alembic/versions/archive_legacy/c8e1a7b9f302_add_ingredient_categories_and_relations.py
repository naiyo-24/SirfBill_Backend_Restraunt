"""add_ingredient_categories_and_relations

Revision ID: c8e1a7b9f302
Revises: 5579f2f335bf
Create Date: 2026-11-14 15:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c8e1a7b9f302'
down_revision: Union[str, Sequence[str], None] = '5579f2f335bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
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

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ing_cat_outlet ON restaurant_ingredient_categories (outlet_id, is_active);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ing_cat_tenant ON restaurant_ingredient_categories (tenant_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_cat ON restaurant_ingredients (category_id);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_outlet_active ON restaurant_ingredients (outlet_id, is_active);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ingredients_tenant ON restaurant_ingredients (tenant_id);"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ingredients_tenant;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ingredients_outlet_active;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ingredients_cat;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ing_cat_tenant;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_ing_cat_outlet;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS storage_zone;"))
    conn.execute(sa.text("ALTER TABLE restaurant_ingredients DROP COLUMN IF EXISTS category_id;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_ingredient_categories;"))
