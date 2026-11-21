"""upgrade_recipe_schema

Revision ID: b4e6f8a0c2d3
Revises: a2c4e6f8b0d1
Create Date: 2026-11-17 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e6f8a0c2d3'
down_revision: Union[str, Sequence[str], None] = 'a2c4e6f8b0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Update restaurant_recipes table columns
    conn.execute(sa.text("""
        ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE CASCADE;
        ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS modifier_option_id UUID REFERENCES restaurant_modifier_options(id) ON DELETE CASCADE;
        ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS produced_ingredient_id UUID REFERENCES restaurant_ingredients(id) ON DELETE SET NULL;
        ALTER TABLE restaurant_recipes ALTER COLUMN item_id DROP NOT NULL;
    """))

    # 2. Add performance indexes
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_recipes_outlet ON restaurant_recipes (outlet_id);
        CREATE INDEX IF NOT EXISTS idx_recipes_modifier ON restaurant_recipes (modifier_option_id);
        CREATE INDEX IF NOT EXISTS idx_recipes_produced_ing ON restaurant_recipes (produced_ingredient_id);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DROP INDEX IF EXISTS idx_recipes_produced_ing;
        DROP INDEX IF EXISTS idx_recipes_modifier;
        DROP INDEX IF EXISTS idx_recipes_outlet;
        ALTER TABLE restaurant_recipes DROP COLUMN IF EXISTS produced_ingredient_id;
        ALTER TABLE restaurant_recipes DROP COLUMN IF EXISTS modifier_option_id;
        ALTER TABLE restaurant_recipes DROP COLUMN IF EXISTS outlet_id;
    """))
