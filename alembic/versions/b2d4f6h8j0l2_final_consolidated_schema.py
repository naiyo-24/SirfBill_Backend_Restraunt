"""final_consolidated_schema

Single consolidated baseline migration for SirfBill Restaurant Platform.
Covers all 40 active production tables across POS, Menu, KDS, Inventory,
Procurement, Recipes, CRM, Loyalty, Subscriptions, and Hardware Marketplace.

Revision ID: b2d4f6h8j0l2
Revises: None
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from models.database import Base
import models

revision: str = 'b2d4f6h8j0l2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Create all consolidated tables in topological dependency order
    for table in Base.metadata.sorted_tables:
        table.create(bind=conn, checkfirst=True)

    # Ensure pg_trgm extension exists for high-speed ILIKE searches
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=conn, checkfirst=True)
