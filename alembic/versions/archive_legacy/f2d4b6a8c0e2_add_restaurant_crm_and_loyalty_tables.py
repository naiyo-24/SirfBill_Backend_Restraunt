"""add_restaurant_crm_and_loyalty_tables

Revision ID: f2d4b6a8c0e2
Revises: e5f7a9b1c3d2
Create Date: 2026-11-20 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2d4b6a8c0e2'
down_revision: Union[str, Sequence[str], None] = 'e5f7a9b1c3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add CRM, RFM, dietary, and Khata fields to restaurant_customers
    conn.execute(sa.text("""
        ALTER TABLE restaurant_customers 
            ADD COLUMN IF NOT EXISTS home_outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS dob DATE,
            ADD COLUMN IF NOT EXISTS anniversary DATE,
            ADD COLUMN IF NOT EXISTS gst_number VARCHAR(20),
            ADD COLUMN IF NOT EXISTS preferences JSON DEFAULT '{}'::json,
            ADD COLUMN IF NOT EXISTS tags JSON DEFAULT '["NEW"]'::json,
            ADD COLUMN IF NOT EXISTS total_visits INTEGER DEFAULT 0 NOT NULL,
            ADD COLUMN IF NOT EXISTS total_spent NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
            ADD COLUMN IF NOT EXISTS avg_order_value NUMERIC(10, 2) DEFAULT 0.00 NOT NULL,
            ADD COLUMN IF NOT EXISTS last_visit_at TIMESTAMP WITHOUT TIME ZONE,
            ADD COLUMN IF NOT EXISTS loyalty_points INTEGER DEFAULT 0 NOT NULL,
            ADD COLUMN IF NOT EXISTS credit_balance NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
            ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
            ADD COLUMN IF NOT EXISTS opt_in_marketing BOOLEAN DEFAULT true NOT NULL,
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_restaurant_customers_home_outlet ON restaurant_customers(home_outlet_id);
    """))

    # 2. Add balance_after to restaurant_loyalty_ledger
    conn.execute(sa.text("""
        ALTER TABLE restaurant_loyalty_ledger
            ADD COLUMN IF NOT EXISTS balance_after INTEGER DEFAULT 0 NOT NULL;
    """))

    # 3. Create restaurant_loyalty_rules table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS restaurant_loyalty_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID UNIQUE NOT NULL,
            outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
            earn_per_rupees NUMERIC(10, 2) NOT NULL DEFAULT 100.00,
            point_value_inr NUMERIC(10, 2) NOT NULL DEFAULT 1.00,
            min_order_for_redeem NUMERIC(10, 2) NOT NULL DEFAULT 200.00,
            max_redeem_pct NUMERIC(5, 2) NOT NULL DEFAULT 20.00,
            points_expiry_days INTEGER NOT NULL DEFAULT 180,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_loyalty_rules_tenant ON restaurant_loyalty_rules (tenant_id);
    """))

    # 4. Create restaurant_customer_credit_ledger (Khata Ledger)
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS restaurant_customer_credit_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES restaurant_customers(id) ON DELETE CASCADE,
            outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            order_id UUID REFERENCES restaurant_orders(id) ON DELETE SET NULL,
            transaction_type VARCHAR(20) NOT NULL,
            amount NUMERIC(12, 2) NOT NULL,
            balance_after NUMERIC(12, 2) NOT NULL,
            payment_mode VARCHAR(50),
            notes TEXT,
            idempotency_key VARCHAR(100) UNIQUE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_cust ON restaurant_customer_credit_ledger (customer_id);
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_outlet ON restaurant_customer_credit_ledger (outlet_id);
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_tenant ON restaurant_customer_credit_ledger (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_idemp ON restaurant_customer_credit_ledger (idempotency_key);
    """))

    # 5. Create restaurant_crm_notifications audit table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS restaurant_crm_notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID REFERENCES restaurant_customers(id) ON DELETE CASCADE,
            outlet_id UUID NOT NULL REFERENCES restaurant_outlets(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            channel VARCHAR(20) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            recipient VARCHAR(120) NOT NULL,
            message_body TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'SENT',
            provider_ref VARCHAR(100),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_crm_notif_cust ON restaurant_crm_notifications (customer_id);
        CREATE INDEX IF NOT EXISTS idx_crm_notif_outlet ON restaurant_crm_notifications (outlet_id);
        CREATE INDEX IF NOT EXISTS idx_crm_notif_tenant ON restaurant_crm_notifications (tenant_id);
    """))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_crm_notifications CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_customer_credit_ledger CASCADE;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS restaurant_loyalty_rules CASCADE;"))

    conn.execute(sa.text("""
        ALTER TABLE restaurant_loyalty_ledger
            DROP COLUMN IF EXISTS balance_after;

        ALTER TABLE restaurant_customers
            DROP COLUMN IF EXISTS home_outlet_id,
            DROP COLUMN IF EXISTS dob,
            DROP COLUMN IF EXISTS anniversary,
            DROP COLUMN IF EXISTS gst_number,
            DROP COLUMN IF EXISTS preferences,
            DROP COLUMN IF EXISTS tags,
            DROP COLUMN IF EXISTS total_visits,
            DROP COLUMN IF EXISTS total_spent,
            DROP COLUMN IF EXISTS avg_order_value,
            DROP COLUMN IF EXISTS last_visit_at,
            DROP COLUMN IF EXISTS loyalty_points,
            DROP COLUMN IF EXISTS credit_balance,
            DROP COLUMN IF EXISTS credit_limit,
            DROP COLUMN IF EXISTS opt_in_marketing,
            DROP COLUMN IF EXISTS notes,
            DROP COLUMN IF EXISTS is_active;
    """))
