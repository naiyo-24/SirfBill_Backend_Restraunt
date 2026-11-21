"""add_restaurant_subscription_tables

Revision ID: e5f7a9b1c3d2
Revises: b4e6f8a0c2d3
Create Date: 2026-11-18 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f7a9b1c3d2'
down_revision: Union[str, Sequence[str], None] = 'b4e6f8a0c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create subscription_plans table
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
            is_active BOOLEAN NOT NULL DEFAULT true,
            is_popular BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sub_plans_code ON subscription_plans (plan_code);
    """))

    # 2. Create tenant_subscriptions table
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
            auto_renew BOOLEAN NOT NULL DEFAULT true,
            purchased_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_tenant ON tenant_subscriptions (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_outlet ON tenant_subscriptions (outlet_id);
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_plan ON tenant_subscriptions (plan_id);
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_status ON tenant_subscriptions (status);
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_expires ON tenant_subscriptions (expires_at);
        CREATE INDEX IF NOT EXISTS idx_tenant_sub_inv ON tenant_subscriptions (invoice_number);
    """))

    # 3. Create subscription_payments audit log table
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
        CREATE INDEX IF NOT EXISTS idx_sub_payments_sub ON subscription_payments (subscription_id);
        CREATE INDEX IF NOT EXISTS idx_sub_payments_tenant ON subscription_payments (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_sub_payments_gateway_pay ON subscription_payments (gateway_payment_id);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DROP TABLE IF EXISTS subscription_payments CASCADE;
        DROP TABLE IF EXISTS tenant_subscriptions CASCADE;
        DROP TABLE IF EXISTS subscription_plans CASCADE;
    """))
