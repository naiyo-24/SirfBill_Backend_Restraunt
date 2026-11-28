"""final_consolidated_schema

Single consolidated baseline migration for SirfBill Restaurant Platform.
Authoritative DDL schema definition for all 40 production tables across
POS, Menu, KDS, Inventory, Procurement, Recipes, CRM, Loyalty, Subscriptions,
and Hardware Marketplace.

Revision ID: b2d4f6h8j0l2
Revises: None
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2d4f6h8j0l2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. Essential PostgreSQL Extensions
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"))

    # --- Table: hardware_products ---
    if 'hardware_products' not in existing_tables:
        op.create_table('hardware_products',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('sku', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('brand', sa.String(length=100), nullable=False),
        sa.Column('model_number', sa.String(length=100), nullable=True),
        sa.Column('short_description', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('specifications', sa.JSON(), nullable=False),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('mrp', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('primary_image_url', sa.Text(), nullable=True),
        sa.Column('images', sa.JSON(), nullable=False),
        sa.Column('stock_quantity', sa.Integer(), nullable=False),
        sa.Column('in_stock', sa.Boolean(), nullable=False),
        sa.Column('warranty_months', sa.Integer(), nullable=False),
        sa.Column('is_popular', sa.Boolean(), nullable=False),
        sa.Column('is_featured', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_hardware_products_name'), 'hardware_products', ['name'], unique=False)
        op.create_index(op.f('ix_hardware_products_category'), 'hardware_products', ['category'], unique=False)
        op.create_index(op.f('ix_hardware_products_sku'), 'hardware_products', ['sku'], unique=True)

    # --- Table: shops ---
    if 'shops' not in existing_tables:
        op.create_table('shops',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=False),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('contact_number', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=True),
        sa.Column('account_holder_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_shops_tenant_id'), 'shops', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_shops_code'), 'shops', ['code'], unique=True)

    # --- Table: subscription_plans ---
    if 'subscription_plans' not in existing_tables:
        op.create_table('subscription_plans',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('plan_code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('billing_cycle', sa.String(length=20), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=False),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_popular', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_subscription_plans_plan_code'), 'subscription_plans', ['plan_code'], unique=True)

    # --- Table: service_plans ---
    if 'service_plans' not in existing_tables:
        op.create_table('service_plans',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('plan_code', sa.String(length=50), nullable=False),
        sa.Column('badge', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('gst_applicable', sa.Boolean(), nullable=False),
        sa.Column('gst_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_service_plans_category'), 'service_plans', ['category'], unique=False)
        op.create_index(op.f('ix_service_plans_plan_code'), 'service_plans', ['plan_code'], unique=True)

    # --- Table: users ---
    if 'users' not in existing_tables:
        op.create_table('users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('avatar_url', sa.String(), nullable=True),
        sa.Column('saved_addresses', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_users_outlet_id'), 'users', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
        op.create_index(op.f('ix_users_phone'), 'users', ['phone'], unique=False)

    # --- Table: distributors ---
    if 'distributors' not in existing_tables:
        op.create_table('distributors',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('shop_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('contact_person', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('gstin', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_distributors_name'), 'distributors', ['name'], unique=False)
        op.create_index(op.f('ix_distributors_tenant_id'), 'distributors', ['tenant_id'], unique=False)

    # --- Table: restaurant_outlets ---
    if 'restaurant_outlets' not in existing_tables:
        op.create_table('restaurant_outlets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('shop_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('service_settings', sa.JSON(), nullable=True),
        sa.Column('allow_negative_stock', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('pin_code', sa.String(length=20), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('outlet_type', sa.String(length=100), nullable=True),
        sa.Column('gstin', sa.String(length=50), nullable=True),
        sa.Column('fssai', sa.String(length=50), nullable=True),
        sa.Column('invoice_prefix', sa.String(length=50), nullable=True),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('opening_time', sa.String(length=20), nullable=True),
        sa.Column('closing_time', sa.String(length=20), nullable=True),
        sa.Column('weekly_closing', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('logo_url', sa.String(), nullable=True),
        sa.Column('upi_id', sa.String(length=100), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('bank_account_no', sa.String(length=50), nullable=True),
        sa.Column('bank_ifsc', sa.String(length=30), nullable=True),
        sa.Column('bank_branch', sa.String(length=100), nullable=True),
        sa.Column('bank_account_name', sa.String(length=150), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_outlets_code'), 'restaurant_outlets', ['code'], unique=False)
        op.create_index(op.f('ix_restaurant_outlets_tenant_id'), 'restaurant_outlets', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_outlets_shop_id'), 'restaurant_outlets', ['shop_id'], unique=False)

    # --- Table: shop_settings ---
    if 'shop_settings' not in existing_tables:
        op.create_table('shop_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('shop_id', sa.UUID(), nullable=True),
        sa.Column('shop_name', sa.String(), nullable=True),
        sa.Column('tagline', sa.String(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('landline', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('gst_number', sa.String(), nullable=True),
        sa.Column('drug_licence', sa.String(), nullable=True),
        sa.Column('cin_number', sa.String(), nullable=True),
        sa.Column('bank_name', sa.String(), nullable=True),
        sa.Column('branch_name', sa.String(), nullable=True),
        sa.Column('ac_holder_name', sa.String(), nullable=True),
        sa.Column('ac_number', sa.String(), nullable=True),
        sa.Column('ifsc_code', sa.String(), nullable=True),
        sa.Column('upi_id', sa.String(), nullable=True),
        sa.Column('terms_1', sa.Text(), nullable=True),
        sa.Column('terms_2', sa.Text(), nullable=True),
        sa.Column('terms_3', sa.Text(), nullable=True),
        sa.Column('logo_url', sa.String(), nullable=True),
        sa.Column('qr_url', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ),
        sa.PrimaryKeyConstraint('id')
        )

    # --- Table: hardware_orders ---
    if 'hardware_orders' not in existing_tables:
        op.create_table('hardware_orders',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('order_number', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('plan_id', sa.String(length=100), nullable=True),
        sa.Column('plan_name', sa.String(length=150), nullable=True),
        sa.Column('plan_price', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('order_type', sa.String(length=30), server_default='HARDWARE', nullable=False),
        sa.Column('order_source', sa.String(length=30), server_default='DASHBOARD', nullable=False),
        sa.Column('contact_name', sa.String(length=150), nullable=False),
        sa.Column('contact_phone', sa.String(length=30), nullable=False),
        sa.Column('contact_email', sa.String(length=120), nullable=True),
        sa.Column('shipping_address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('pincode', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('payment_status', sa.String(length=30), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('payment_reference', sa.String(length=100), nullable=True),
        sa.Column('tracking_number', sa.String(length=100), nullable=True),
        sa.Column('courier_partner', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['product_id'], ['hardware_products.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_hardware_orders_product_id'), 'hardware_orders', ['product_id'], unique=False)
        op.create_index(op.f('ix_hardware_orders_order_number'), 'hardware_orders', ['order_number'], unique=True)
        op.create_index(op.f('ix_hardware_orders_outlet_id'), 'hardware_orders', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_hardware_orders_status'), 'hardware_orders', ['status'], unique=False)
        op.create_index(op.f('ix_hardware_orders_tenant_id'), 'hardware_orders', ['tenant_id'], unique=False)

    # --- Table: restaurant_audit_events ---
    if 'restaurant_audit_events' not in existing_tables:
        op.create_table('restaurant_audit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('entity_name', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('before_state', sa.JSON(), nullable=True),
        sa.Column('after_state', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_audit_events_tenant_id'), 'restaurant_audit_events', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_audit_events_outlet_id'), 'restaurant_audit_events', ['outlet_id'], unique=False)

    # --- Table: restaurant_customers ---
    if 'restaurant_customers' not in existing_tables:
        op.create_table('restaurant_customers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('home_outlet_id', sa.UUID(), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('dob', sa.Date(), nullable=True),
        sa.Column('anniversary', sa.Date(), nullable=True),
        sa.Column('gst_number', sa.String(length=20), nullable=True),
        sa.Column('preferences', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('total_visits', sa.Integer(), nullable=False),
        sa.Column('total_spent', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('avg_order_value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('last_visit_at', sa.DateTime(), nullable=True),
        sa.Column('loyalty_points', sa.Integer(), nullable=False),
        sa.Column('credit_balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('credit_limit', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('opt_in_marketing', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['home_outlet_id'], ['restaurant_outlets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_customers_tenant_id'), 'restaurant_customers', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_customers_phone'), 'restaurant_customers', ['phone'], unique=False)
        op.create_index(op.f('ix_restaurant_customers_outlet_id'), 'restaurant_customers', ['outlet_id'], unique=False)

    # --- Table: restaurant_ingredient_categories ---
    if 'restaurant_ingredient_categories' not in existing_tables:
        op.create_table('restaurant_ingredient_categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('storage_zone_temp', sa.String(length=150), nullable=True),
        sa.Column('color_code', sa.String(length=30), nullable=True),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_ingredient_categories_code'), 'restaurant_ingredient_categories', ['code'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredient_categories_tenant_id'), 'restaurant_ingredient_categories', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredient_categories_outlet_id'), 'restaurant_ingredient_categories', ['outlet_id'], unique=False)

    # --- Table: restaurant_loyalty_rules ---
    if 'restaurant_loyalty_rules' not in existing_tables:
        op.create_table('restaurant_loyalty_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('earn_per_rupees', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('point_value_inr', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('min_order_for_redeem', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('max_redeem_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('points_expiry_days', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_loyalty_rules_tenant_id'), 'restaurant_loyalty_rules', ['tenant_id'], unique=True)

    # --- Table: restaurant_menu_categories ---
    if 'restaurant_menu_categories' not in existing_tables:
        op.create_table('restaurant_menu_categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon_emoji', sa.String(length=50), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_menu_categories_tenant_id'), 'restaurant_menu_categories', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_menu_categories_outlet_id'), 'restaurant_menu_categories', ['outlet_id'], unique=False)

    # --- Table: restaurant_modifier_groups ---
    if 'restaurant_modifier_groups' not in existing_tables:
        op.create_table('restaurant_modifier_groups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('min_selection', sa.Integer(), nullable=False),
        sa.Column('max_selection', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('applicable_item_ids', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_modifier_groups_tenant_id'), 'restaurant_modifier_groups', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_modifier_groups_outlet_id'), 'restaurant_modifier_groups', ['outlet_id'], unique=False)

    # --- Table: restaurant_shifts ---
    if 'restaurant_shifts' not in existing_tables:
        op.create_table('restaurant_shifts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('cashier_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('opened_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('opening_cash', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('counted_cash', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('expected_cash', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('variance', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['cashier_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_shifts_tenant_id'), 'restaurant_shifts', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_shifts_outlet_id'), 'restaurant_shifts', ['outlet_id'], unique=False)

    # --- Table: restaurant_stock_audits ---
    if 'restaurant_stock_audits' not in existing_tables:
        op.create_table('restaurant_stock_audits',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('batch_code', sa.String(length=100), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('auditor_id', sa.UUID(), nullable=True),
        sa.Column('audit_date', sa.Date(), nullable=False),
        sa.Column('audit_started_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('total_items_audited', sa.Integer(), nullable=False),
        sa.Column('items_adjusted', sa.Integer(), nullable=False),
        sa.Column('total_surplus_rupees', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_deficit_rupees', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('net_variance_rupees', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['auditor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_stock_audits_auditor_id'), 'restaurant_stock_audits', ['auditor_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_audits_batch_code'), 'restaurant_stock_audits', ['batch_code'], unique=True)
        op.create_index(op.f('ix_restaurant_stock_audits_tenant_id'), 'restaurant_stock_audits', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_audits_outlet_id'), 'restaurant_stock_audits', ['outlet_id'], unique=False)

    # --- Table: restaurant_stock_transfers ---
    if 'restaurant_stock_transfers' not in existing_tables:
        op.create_table('restaurant_stock_transfers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('transfer_number', sa.String(length=50), nullable=False),
        sa.Column('transfer_type', sa.String(length=30), nullable=False),
        sa.Column('from_outlet_id', sa.UUID(), nullable=False),
        sa.Column('to_outlet_id', sa.UUID(), nullable=False),
        sa.Column('from_station', sa.String(length=100), nullable=True),
        sa.Column('to_station', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('initiated_by_id', sa.UUID(), nullable=True),
        sa.Column('dispatched_by_id', sa.UUID(), nullable=True),
        sa.Column('received_by_id', sa.UUID(), nullable=True),
        sa.Column('dispatched_at', sa.DateTime(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('vehicle_number', sa.String(length=50), nullable=True),
        sa.Column('driver_name', sa.String(length=100), nullable=True),
        sa.Column('driver_phone', sa.String(length=50), nullable=True),
        sa.Column('sender_signature', sa.Text(), nullable=True),
        sa.Column('driver_signature', sa.Text(), nullable=True),
        sa.Column('receiver_signature', sa.Text(), nullable=True),
        sa.Column('total_items', sa.Integer(), nullable=False),
        sa.Column('total_valuation', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['dispatched_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['from_outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['initiated_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['received_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_stock_transfers_from_outlet_id'), 'restaurant_stock_transfers', ['from_outlet_id'], unique=False)
        op.create_index('idx_stock_transfers_status', 'restaurant_stock_transfers', ['tenant_id', 'status'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_transfers_tenant_id'), 'restaurant_stock_transfers', ['tenant_id'], unique=False)
        op.create_index('idx_stock_transfers_tenant_number', 'restaurant_stock_transfers', ['tenant_id', 'transfer_number'], unique=True)
        op.create_index('idx_stock_transfers_dates', 'restaurant_stock_transfers', ['created_at'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_transfers_to_outlet_id'), 'restaurant_stock_transfers', ['to_outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_transfers_status'), 'restaurant_stock_transfers', ['status'], unique=False)

    # --- Table: restaurant_suppliers ---
    if 'restaurant_suppliers' not in existing_tables:
        op.create_table('restaurant_suppliers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('contact_person', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('gstin', sa.String(length=50), nullable=True),
        sa.Column('fssai', sa.String(length=50), nullable=True),
        sa.Column('payment_terms', sa.String(length=50), nullable=True),
        sa.Column('bank_details', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_suppliers_name'), 'restaurant_suppliers', ['name'], unique=False)
        op.create_index(op.f('ix_restaurant_suppliers_code'), 'restaurant_suppliers', ['code'], unique=False)
        op.create_index(op.f('ix_restaurant_suppliers_outlet_id'), 'restaurant_suppliers', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_suppliers_tenant_id'), 'restaurant_suppliers', ['tenant_id'], unique=False)

    # --- Table: restaurant_tables ---
    if 'restaurant_tables' not in existing_tables:
        op.create_table('restaurant_tables',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('table_code', sa.String(length=50), nullable=False),
        sa.Column('section', sa.String(length=50), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_tables_tenant_id'), 'restaurant_tables', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_tables_outlet_id'), 'restaurant_tables', ['outlet_id'], unique=False)

    # --- Table: tenant_subscriptions ---
    if 'tenant_subscriptions' not in existing_tables:
        op.create_table('tenant_subscriptions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('price_paid', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('payment_reference', sa.String(length=100), nullable=True),
        sa.Column('invoice_number', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), nullable=False),
        sa.Column('purchased_by_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['purchased_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_tenant_subscriptions_status'), 'tenant_subscriptions', ['status'], unique=False)
        op.create_index(op.f('ix_tenant_subscriptions_expires_at'), 'tenant_subscriptions', ['expires_at'], unique=False)
        op.create_index(op.f('ix_tenant_subscriptions_plan_id'), 'tenant_subscriptions', ['plan_id'], unique=False)
        op.create_index(op.f('ix_tenant_subscriptions_tenant_id'), 'tenant_subscriptions', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_tenant_subscriptions_outlet_id'), 'tenant_subscriptions', ['outlet_id'], unique=False)

    # --- Table: restaurant_crm_notifications ---
    if 'restaurant_crm_notifications' not in existing_tables:
        op.create_table('restaurant_crm_notifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('recipient', sa.String(length=120), nullable=False),
        sa.Column('message_body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('provider_ref', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['restaurant_customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_crm_notifications_customer_id'), 'restaurant_crm_notifications', ['customer_id'], unique=False)
        op.create_index(op.f('ix_restaurant_crm_notifications_tenant_id'), 'restaurant_crm_notifications', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_crm_notifications_outlet_id'), 'restaurant_crm_notifications', ['outlet_id'], unique=False)

    # --- Table: restaurant_ingredients ---
    if 'restaurant_ingredients' not in existing_tables:
        op.create_table('restaurant_ingredients',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('sku', sa.String(length=50), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('storage_zone', sa.String(length=100), nullable=True),
        sa.Column('storage_location', sa.String(length=100), nullable=True),
        sa.Column('current_stock', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('reorder_level', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('cost_per_unit', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('purchase_uom', sa.String(length=20), nullable=True),
        sa.Column('recipe_uom', sa.String(length=20), nullable=True),
        sa.Column('uom_conversion_factor', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('min_par_level', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('ideal_par_level', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('cost_per_purchase_unit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('primary_supplier_id', sa.UUID(), nullable=True),
        sa.Column('is_perishable', sa.Boolean(), nullable=False),
        sa.Column('shelf_life_days', sa.Integer(), nullable=True),
        sa.Column('last_restocked_at', sa.DateTime(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['restaurant_ingredient_categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['primary_supplier_id'], ['restaurant_suppliers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_ingredients_outlet_id'), 'restaurant_ingredients', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredients_primary_supplier_id'), 'restaurant_ingredients', ['primary_supplier_id'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredients_sku'), 'restaurant_ingredients', ['sku'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredients_category_id'), 'restaurant_ingredients', ['category_id'], unique=False)
        op.create_index(op.f('ix_restaurant_ingredients_tenant_id'), 'restaurant_ingredients', ['tenant_id'], unique=False)

    # --- Table: restaurant_menu_items ---
    if 'restaurant_menu_items' not in existing_tables:
        op.create_table('restaurant_menu_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('short_code', sa.String(length=30), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(), nullable=True),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('prep_station', sa.String(length=50), nullable=False),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('takeaway_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('delivery_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('variant_prices', sa.JSON(), nullable=True),
        sa.Column('badge', sa.String(length=50), nullable=True),
        sa.Column('is_available', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['restaurant_menu_categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_menu_items_category_id'), 'restaurant_menu_items', ['category_id'], unique=False)
        op.create_index(op.f('ix_restaurant_menu_items_tenant_id'), 'restaurant_menu_items', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_menu_items_short_code'), 'restaurant_menu_items', ['short_code'], unique=False)
        op.create_index(op.f('ix_restaurant_menu_items_outlet_id'), 'restaurant_menu_items', ['outlet_id'], unique=False)

    # --- Table: restaurant_orders ---
    if 'restaurant_orders' not in existing_tables:
        op.create_table('restaurant_orders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('order_number', sa.String(length=50), nullable=False),
        sa.Column('order_type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('table_id', sa.UUID(), nullable=True),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('customer_name', sa.String(length=150), nullable=True),
        sa.Column('customer_phone', sa.String(length=20), nullable=True),
        sa.Column('waiter_id', sa.UUID(), nullable=True),
        sa.Column('shift_id', sa.UUID(), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('discount_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('discount_reason', sa.String(length=200), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('rounding_adjustment', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('grand_total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('paid_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['restaurant_customers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_id'], ['restaurant_shifts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['table_id'], ['restaurant_tables.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['waiter_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_orders_outlet_id'), 'restaurant_orders', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_orders_status'), 'restaurant_orders', ['status'], unique=False)
        op.create_index(op.f('ix_restaurant_orders_table_id'), 'restaurant_orders', ['table_id'], unique=False)
        op.create_index(op.f('ix_restaurant_orders_order_number'), 'restaurant_orders', ['order_number'], unique=False)
        op.create_index(op.f('ix_restaurant_orders_tenant_id'), 'restaurant_orders', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_orders_idempotency_key'), 'restaurant_orders', ['idempotency_key'], unique=True)

    # --- Table: restaurant_purchase_orders ---
    if 'restaurant_purchase_orders' not in existing_tables:
        op.create_table('restaurant_purchase_orders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('po_number', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('order_date', sa.Date(), nullable=False),
        sa.Column('expected_delivery_date', sa.Date(), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('delivery_address', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.UUID(), nullable=True),
        sa.Column('approved_by_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['supplier_id'], ['restaurant_suppliers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_purchase_orders_outlet_id'), 'restaurant_purchase_orders', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_purchase_orders_supplier_id'), 'restaurant_purchase_orders', ['supplier_id'], unique=False)
        op.create_index(op.f('ix_restaurant_purchase_orders_po_number'), 'restaurant_purchase_orders', ['po_number'], unique=False)
        op.create_index(op.f('ix_restaurant_purchase_orders_tenant_id'), 'restaurant_purchase_orders', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_purchase_orders_status'), 'restaurant_purchase_orders', ['status'], unique=False)

    # --- Table: subscription_payments ---
    if 'subscription_payments' not in existing_tables:
        op.create_table('subscription_payments',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('subscription_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('payment_gateway', sa.String(length=50), nullable=False),
        sa.Column('gateway_order_id', sa.String(length=100), nullable=True),
        sa.Column('gateway_payment_id', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('payment_date', sa.DateTime(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['tenant_subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_subscription_payments_tenant_id'), 'subscription_payments', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_subscription_payments_subscription_id'), 'subscription_payments', ['subscription_id'], unique=False)

    # --- Table: restaurant_customer_ledger ---
    if 'restaurant_customer_ledger' not in existing_tables:
        op.create_table('restaurant_customer_ledger',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('order_id', sa.UUID(), nullable=True),
        sa.Column('ledger_type', sa.String(length=30), nullable=False),
        sa.Column('transaction_type', sa.String(length=30), nullable=False),
        sa.Column('points_delta', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('balance_after', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('payment_mode', sa.String(length=50), nullable=True),
        sa.Column('reason', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['restaurant_customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['restaurant_orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_customer_ledger_outlet_id'), 'restaurant_customer_ledger', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_customer_ledger_idempotency_key'), 'restaurant_customer_ledger', ['idempotency_key'], unique=True)
        op.create_index(op.f('ix_restaurant_customer_ledger_tenant_id'), 'restaurant_customer_ledger', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_customer_ledger_order_id'), 'restaurant_customer_ledger', ['order_id'], unique=False)
        op.create_index(op.f('ix_restaurant_customer_ledger_customer_id'), 'restaurant_customer_ledger', ['customer_id'], unique=False)

    # --- Table: restaurant_grn ---
    if 'restaurant_grn' not in existing_tables:
        op.create_table('restaurant_grn',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('po_id', sa.UUID(), nullable=True),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('grn_number', sa.String(length=50), nullable=False),
        sa.Column('supplier_invoice_no', sa.String(length=100), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('invoice_document_url', sa.String(length=500), nullable=True),
        sa.Column('received_date', sa.DateTime(), nullable=False),
        sa.Column('received_by_id', sa.UUID(), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('payment_status', sa.String(length=30), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['po_id'], ['restaurant_purchase_orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['received_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['supplier_id'], ['restaurant_suppliers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_grn_supplier_id'), 'restaurant_grn', ['supplier_id'], unique=False)
        op.create_index(op.f('ix_restaurant_grn_tenant_id'), 'restaurant_grn', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_grn_po_id'), 'restaurant_grn', ['po_id'], unique=False)
        op.create_index(op.f('ix_restaurant_grn_outlet_id'), 'restaurant_grn', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_grn_grn_number'), 'restaurant_grn', ['grn_number'], unique=False)

    # --- Table: restaurant_kitchen_tickets ---
    if 'restaurant_kitchen_tickets' not in existing_tables:
        op.create_table('restaurant_kitchen_tickets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('ticket_number', sa.String(length=50), nullable=False),
        sa.Column('station', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('server_user_id', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_reprint', sa.Boolean(), nullable=False),
        sa.Column('reprint_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['restaurant_orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['server_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_kitchen_tickets_order_id'), 'restaurant_kitchen_tickets', ['order_id'], unique=False)

    # --- Table: restaurant_order_lines ---
    if 'restaurant_order_lines' not in existing_tables:
        op.create_table('restaurant_order_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=True),
        sa.Column('item_name', sa.String(length=150), nullable=False),
        sa.Column('variant_name', sa.String(length=50), nullable=False),
        sa.Column('prep_station', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('modifier_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('discount_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('line_total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('selected_modifiers', sa.JSON(), nullable=True),
        sa.Column('special_instructions', sa.Text(), nullable=True),
        sa.Column('kot_status', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['restaurant_menu_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['restaurant_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_order_lines_order_id'), 'restaurant_order_lines', ['order_id'], unique=False)

    # --- Table: restaurant_purchase_order_items ---
    if 'restaurant_purchase_order_items' not in existing_tables:
        op.create_table('restaurant_purchase_order_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('po_id', sa.UUID(), nullable=False),
        sa.Column('ingredient_id', sa.UUID(), nullable=False),
        sa.Column('quantity_ordered', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_received', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total_price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['ingredient_id'], ['restaurant_ingredients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['po_id'], ['restaurant_purchase_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_purchase_order_items_po_id'), 'restaurant_purchase_order_items', ['po_id'], unique=False)
        op.create_index(op.f('ix_restaurant_purchase_order_items_ingredient_id'), 'restaurant_purchase_order_items', ['ingredient_id'], unique=False)

    # --- Table: restaurant_recipes ---
    if 'restaurant_recipes' not in existing_tables:
        op.create_table('restaurant_recipes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=True),
        sa.Column('item_id', sa.UUID(), nullable=True),
        sa.Column('modifier_option_id', sa.UUID(), nullable=True),
        sa.Column('produced_ingredient_id', sa.UUID(), nullable=True),
        sa.Column('variant_name', sa.String(length=50), nullable=False),
        sa.Column('yield_servings', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['restaurant_menu_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['produced_ingredient_id'], ['restaurant_ingredients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_recipes_modifier_option_id'), 'restaurant_recipes', ['modifier_option_id'], unique=False)
        op.create_index(op.f('ix_restaurant_recipes_produced_ingredient_id'), 'restaurant_recipes', ['produced_ingredient_id'], unique=False)
        op.create_index(op.f('ix_restaurant_recipes_item_id'), 'restaurant_recipes', ['item_id'], unique=False)
        op.create_index(op.f('ix_restaurant_recipes_outlet_id'), 'restaurant_recipes', ['outlet_id'], unique=False)

    # --- Table: restaurant_stock_audit_items ---
    if 'restaurant_stock_audit_items' not in existing_tables:
        op.create_table('restaurant_stock_audit_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('audit_id', sa.UUID(), nullable=False),
        sa.Column('ingredient_id', sa.UUID(), nullable=False),
        sa.Column('ingredient_name', sa.String(length=150), nullable=True),
        sa.Column('recipe_uom', sa.String(length=20), nullable=False),
        sa.Column('purchase_uom', sa.String(length=20), nullable=True),
        sa.Column('input_uom', sa.String(length=20), nullable=True),
        sa.Column('previous_stock', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('expected_stock', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('physical_count', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('raw_input_count', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('variance', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit_cost_at_time', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('variance_rupees', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['audit_id'], ['restaurant_stock_audits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['restaurant_ingredients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_stock_audit_items_audit_id'), 'restaurant_stock_audit_items', ['audit_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_audit_items_ingredient_id'), 'restaurant_stock_audit_items', ['ingredient_id'], unique=False)

    # --- Table: restaurant_stock_ledger ---
    if 'restaurant_stock_ledger' not in existing_tables:
        op.create_table('restaurant_stock_ledger',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ingredient_id', sa.UUID(), nullable=False),
        sa.Column('outlet_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('signed_quantity', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit_cost_at_time', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=True),
        sa.Column('source_id', sa.String(length=100), nullable=True),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['restaurant_ingredients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['outlet_id'], ['restaurant_outlets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_stock_ledger_outlet_id'), 'restaurant_stock_ledger', ['outlet_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_ledger_ingredient_id'), 'restaurant_stock_ledger', ['ingredient_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_ledger_tenant_id'), 'restaurant_stock_ledger', ['tenant_id'], unique=False)

    # --- Table: restaurant_stock_transfer_items ---
    if 'restaurant_stock_transfer_items' not in existing_tables:
        op.create_table('restaurant_stock_transfer_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('transfer_id', sa.UUID(), nullable=False),
        sa.Column('ingredient_id', sa.UUID(), nullable=False),
        sa.Column('destination_ingredient_id', sa.UUID(), nullable=True),
        sa.Column('ingredient_name', sa.String(length=150), nullable=False),
        sa.Column('sku', sa.String(length=50), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('quantity_requested', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_dispatched', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_received', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_variance', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('variance_reason', sa.String(length=255), nullable=True),
        sa.Column('batch_number', sa.String(length=100), nullable=True),
        sa.Column('expiry_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['destination_ingredient_id'], ['restaurant_ingredients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['restaurant_ingredients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['transfer_id'], ['restaurant_stock_transfers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_stock_transfer_items_destination_ingredient_id'), 'restaurant_stock_transfer_items', ['destination_ingredient_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_transfer_items_transfer_id'), 'restaurant_stock_transfer_items', ['transfer_id'], unique=False)
        op.create_index(op.f('ix_restaurant_stock_transfer_items_ingredient_id'), 'restaurant_stock_transfer_items', ['ingredient_id'], unique=False)

    # --- Table: restaurant_tenders ---
    if 'restaurant_tenders' not in existing_tables:
        op.create_table('restaurant_tenders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('method', sa.String(length=30), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('cashier_id', sa.UUID(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['cashier_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['restaurant_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_tenders_idempotency_key'), 'restaurant_tenders', ['idempotency_key'], unique=True)
        op.create_index(op.f('ix_restaurant_tenders_tenant_id'), 'restaurant_tenders', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_restaurant_tenders_order_id'), 'restaurant_tenders', ['order_id'], unique=False)

    # --- Table: restaurant_grn_items ---
    if 'restaurant_grn_items' not in existing_tables:
        op.create_table('restaurant_grn_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('grn_id', sa.UUID(), nullable=False),
        sa.Column('ingredient_id', sa.UUID(), nullable=False),
        sa.Column('po_item_id', sa.UUID(), nullable=True),
        sa.Column('quantity_received', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantity_rejected', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total_price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('batch_number', sa.String(length=50), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['grn_id'], ['restaurant_grn.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['restaurant_ingredients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['po_item_id'], ['restaurant_purchase_order_items.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_grn_items_ingredient_id'), 'restaurant_grn_items', ['ingredient_id'], unique=False)
        op.create_index(op.f('ix_restaurant_grn_items_grn_id'), 'restaurant_grn_items', ['grn_id'], unique=False)

    # --- Table: restaurant_kitchen_events ---
    if 'restaurant_kitchen_events' not in existing_tables:
        op.create_table('restaurant_kitchen_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('from_status', sa.String(length=30), nullable=True),
        sa.Column('to_status', sa.String(length=30), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ticket_id'], ['restaurant_kitchen_tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_kitchen_events_ticket_id'), 'restaurant_kitchen_events', ['ticket_id'], unique=False)

    # --- Table: restaurant_kitchen_ticket_items ---
    if 'restaurant_kitchen_ticket_items' not in existing_tables:
        op.create_table('restaurant_kitchen_ticket_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('order_line_id', sa.UUID(), nullable=False),
        sa.Column('item_name', sa.String(length=150), nullable=False),
        sa.Column('variant_name', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('modifiers_summary', sa.Text(), nullable=True),
        sa.Column('special_instructions', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(['order_line_id'], ['restaurant_order_lines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ticket_id'], ['restaurant_kitchen_tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_kitchen_ticket_items_ticket_id'), 'restaurant_kitchen_ticket_items', ['ticket_id'], unique=False)

    # --- Table: restaurant_refunds ---
    if 'restaurant_refunds' not in existing_tables:
        op.create_table('restaurant_refunds',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tender_id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('authorized_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['authorized_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['restaurant_orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tender_id'], ['restaurant_tenders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_restaurant_refunds_order_id'), 'restaurant_refunds', ['order_id'], unique=False)
        op.create_index(op.f('ix_restaurant_refunds_tender_id'), 'restaurant_refunds', ['tender_id'], unique=False)

    # -------------------------------------------------------------
    # Post-Migration Self-Healing / Schema Sync for Existing Tables
    # Guarantees that even if tables already existed from an older
    # baseline, all newly introduced multi-tenant & branch columns exist!
    # -------------------------------------------------------------
    healing_statements = [
        # users
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id UUID;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS outlet_id UUID;",
        "CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_users_outlet_id ON users(outlet_id);",

        # tenant_subscriptions
        "ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS outlet_id UUID;",
        "CREATE INDEX IF NOT EXISTS ix_tenant_subscriptions_outlet_id ON tenant_subscriptions(outlet_id);",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tenant_subscriptions_outlet_id_fkey') THEN ALTER TABLE tenant_subscriptions ADD CONSTRAINT tenant_subscriptions_outlet_id_fkey FOREIGN KEY (outlet_id) REFERENCES restaurant_outlets(id) ON DELETE SET NULL; END IF; END $$;",

        # restaurant_outlets
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS tenant_id UUID;",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS address TEXT;",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS city VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS state VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS pin_code VARCHAR(20);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS country VARCHAR(100) DEFAULT 'India';",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS phone VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS email VARCHAR(120);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS outlet_type VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS gstin VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS fssai VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS invoice_prefix VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5, 2) DEFAULT 5.0;",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS opening_time VARCHAR(20);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS closing_time VARCHAR(20);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS weekly_closing VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS description TEXT;",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS logo_url VARCHAR;",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS upi_id VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(50);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS bank_ifsc VARCHAR(30);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS bank_branch VARCHAR(100);",
        "ALTER TABLE restaurant_outlets ADD COLUMN IF NOT EXISTS bank_account_name VARCHAR(150);",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_outlets_tenant_id ON restaurant_outlets(tenant_id);",

        # restaurant_menu_categories
        "ALTER TABLE restaurant_menu_categories ADD COLUMN IF NOT EXISTS icon_emoji VARCHAR(50);",
        "ALTER TABLE restaurant_menu_categories ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;",

        # restaurant_menu_items
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS short_code VARCHAR(30);",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS item_type VARCHAR(20) DEFAULT 'NON_VEG';",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS prep_station VARCHAR(50) DEFAULT 'KITCHEN';",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5, 2) DEFAULT 5.00;",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS price NUMERIC(10, 2);",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS takeaway_price NUMERIC(10, 2);",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(10, 2);",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS variant_prices JSON;",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS badge VARCHAR(50);",
        "ALTER TABLE restaurant_menu_items ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE;",

        # restaurant_tables
        "ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS table_code VARCHAR(50);",
        "ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS section VARCHAR(50) DEFAULT 'Main Hall';",
        "ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS capacity INTEGER DEFAULT 4;",
        "ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'VACANT';",
        "ALTER TABLE restaurant_tables ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_tables_outlet_active ON restaurant_tables(outlet_id, is_active);",

        # restaurant_orders
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(30) DEFAULT 'DINE_IN';",
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS customer_name VARCHAR(150);",
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(20);",
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS rounding_adjustment NUMERIC(10, 2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;",
        "ALTER TABLE restaurant_orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);",
        "CREATE INDEX IF NOT EXISTS idx_orders_outlet_status ON restaurant_orders(outlet_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_phone ON restaurant_orders(customer_phone);",

        # restaurant_order_lines
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS variant_name VARCHAR(100);",
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS prep_station VARCHAR(50) DEFAULT 'KITCHEN';",
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS modifier_price NUMERIC(10, 2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS selected_modifiers JSON;",
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS special_instructions TEXT;",
        "ALTER TABLE restaurant_order_lines ADD COLUMN IF NOT EXISTS kot_status VARCHAR(30) DEFAULT 'PENDING';",

        # restaurant_kitchen_tickets & ticket_items
        "ALTER TABLE restaurant_kitchen_tickets ADD COLUMN IF NOT EXISTS station VARCHAR(50) DEFAULT 'KITCHEN';",
        "ALTER TABLE restaurant_kitchen_tickets ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'FIRED';",
        "ALTER TABLE restaurant_kitchen_tickets ADD COLUMN IF NOT EXISTS is_reprint BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE restaurant_kitchen_tickets ADD COLUMN IF NOT EXISTS reprint_count INTEGER DEFAULT 0;",
        "ALTER TABLE restaurant_kitchen_ticket_items ADD COLUMN IF NOT EXISTS variant_name VARCHAR(100);",
        "ALTER TABLE restaurant_kitchen_ticket_items ADD COLUMN IF NOT EXISTS modifiers_summary TEXT;",
        "ALTER TABLE restaurant_kitchen_ticket_items ADD COLUMN IF NOT EXISTS special_instructions TEXT;",
        "ALTER TABLE restaurant_kitchen_ticket_items ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'PENDING';",

        # restaurant_ingredients (inventory & procurement integration)
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS category_id UUID;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS storage_zone VARCHAR(100);",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS storage_location VARCHAR(100);",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS purchase_uom VARCHAR(20) DEFAULT 'KG';",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS recipe_uom VARCHAR(20) DEFAULT 'G';",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS uom_conversion_factor NUMERIC(12, 4) DEFAULT 1.0000;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS min_par_level NUMERIC(12, 3) DEFAULT 0.000;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS ideal_par_level NUMERIC(12, 3) DEFAULT 0.000;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS cost_per_purchase_unit NUMERIC(10, 2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS primary_supplier_id UUID;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS is_perishable BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER;",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS last_restocked_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW();",
        "ALTER TABLE restaurant_ingredients ADD COLUMN IF NOT EXISTS image_url TEXT;",

        # shops
        "ALTER TABLE shops ADD COLUMN IF NOT EXISTS account_holder_name VARCHAR;",

        # High-performance Trigram GIN indexes
        "CREATE INDEX IF NOT EXISTS idx_menu_items_name_trgm ON restaurant_menu_items USING gin (name gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_menu_items_shortcode_trgm ON restaurant_menu_items USING gin (short_code gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_menu_items_outlet_active ON restaurant_menu_items (outlet_id, is_active);",
        "CREATE INDEX IF NOT EXISTS idx_customers_name_trgm ON restaurant_customers USING gin (name gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_customers_phone_trgm ON restaurant_customers USING gin (phone gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_customers_outlet_active ON restaurant_customers (outlet_id, is_active);",
        "CREATE INDEX IF NOT EXISTS idx_users_name_trgm ON users USING gin (name gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_users_phone_trgm ON users USING gin (phone gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_users_tenant_role ON users (tenant_id, role);",

        # restaurant_customer_ledger
        "ALTER TABLE restaurant_customer_ledger ADD COLUMN IF NOT EXISTS tenant_id UUID;",
        "ALTER TABLE restaurant_customer_ledger ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_customer_ledger_tenant_id ON restaurant_customer_ledger(tenant_id);",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_restaurant_customer_ledger_idempotency_key ON restaurant_customer_ledger(idempotency_key);",

        # restaurant_recipes
        "ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS modifier_option_id UUID;",
        "ALTER TABLE restaurant_recipes ADD COLUMN IF NOT EXISTS produced_ingredient_id UUID;",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_recipes_modifier_option_id ON restaurant_recipes(modifier_option_id);",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_recipes_produced_ingredient_id ON restaurant_recipes(produced_ingredient_id);",
        "CREATE INDEX IF NOT EXISTS ix_restaurant_recipes_outlet_id ON restaurant_recipes(outlet_id);",
    ]
    for stmt in healing_statements:
        op.execute(sa.text(stmt))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())
    if 'restaurant_refunds' in existing_tables:
        op.drop_table('restaurant_refunds')
    if 'restaurant_kitchen_ticket_items' in existing_tables:
        op.drop_table('restaurant_kitchen_ticket_items')
    if 'restaurant_kitchen_events' in existing_tables:
        op.drop_table('restaurant_kitchen_events')
    if 'restaurant_grn_items' in existing_tables:
        op.drop_table('restaurant_grn_items')
    if 'restaurant_tenders' in existing_tables:
        op.drop_table('restaurant_tenders')
    if 'restaurant_stock_transfer_items' in existing_tables:
        op.drop_table('restaurant_stock_transfer_items')
    if 'restaurant_stock_ledger' in existing_tables:
        op.drop_table('restaurant_stock_ledger')
    if 'restaurant_stock_audit_items' in existing_tables:
        op.drop_table('restaurant_stock_audit_items')
    if 'restaurant_recipes' in existing_tables:
        op.drop_table('restaurant_recipes')
    if 'restaurant_purchase_order_items' in existing_tables:
        op.drop_table('restaurant_purchase_order_items')
    if 'restaurant_order_lines' in existing_tables:
        op.drop_table('restaurant_order_lines')
    if 'restaurant_kitchen_tickets' in existing_tables:
        op.drop_table('restaurant_kitchen_tickets')
    if 'restaurant_grn' in existing_tables:
        op.drop_table('restaurant_grn')
    if 'restaurant_customer_ledger' in existing_tables:
        op.drop_table('restaurant_customer_ledger')
    if 'subscription_payments' in existing_tables:
        op.drop_table('subscription_payments')
    if 'restaurant_purchase_orders' in existing_tables:
        op.drop_table('restaurant_purchase_orders')
    if 'restaurant_orders' in existing_tables:
        op.drop_table('restaurant_orders')
    if 'restaurant_menu_items' in existing_tables:
        op.drop_table('restaurant_menu_items')
    if 'restaurant_ingredients' in existing_tables:
        op.drop_table('restaurant_ingredients')
    if 'restaurant_crm_notifications' in existing_tables:
        op.drop_table('restaurant_crm_notifications')
    if 'tenant_subscriptions' in existing_tables:
        op.drop_table('tenant_subscriptions')
    if 'restaurant_tables' in existing_tables:
        op.drop_table('restaurant_tables')
    if 'restaurant_suppliers' in existing_tables:
        op.drop_table('restaurant_suppliers')
    if 'restaurant_stock_transfers' in existing_tables:
        op.drop_table('restaurant_stock_transfers')
    if 'restaurant_stock_audits' in existing_tables:
        op.drop_table('restaurant_stock_audits')
    if 'restaurant_shifts' in existing_tables:
        op.drop_table('restaurant_shifts')
    if 'restaurant_modifier_groups' in existing_tables:
        op.drop_table('restaurant_modifier_groups')
    if 'restaurant_menu_categories' in existing_tables:
        op.drop_table('restaurant_menu_categories')
    if 'restaurant_loyalty_rules' in existing_tables:
        op.drop_table('restaurant_loyalty_rules')
    if 'restaurant_ingredient_categories' in existing_tables:
        op.drop_table('restaurant_ingredient_categories')
    if 'restaurant_customers' in existing_tables:
        op.drop_table('restaurant_customers')
    if 'restaurant_audit_events' in existing_tables:
        op.drop_table('restaurant_audit_events')
    if 'hardware_orders' in existing_tables:
        op.drop_table('hardware_orders')
    if 'shop_settings' in existing_tables:
        op.drop_table('shop_settings')
    if 'restaurant_outlets' in existing_tables:
        op.drop_table('restaurant_outlets')
    if 'distributors' in existing_tables:
        op.drop_table('distributors')
    if 'users' in existing_tables:
        op.drop_table('users')
    if 'subscription_plans' in existing_tables:
        op.drop_table('subscription_plans')
    if 'service_plans' in existing_tables:
        op.drop_table('service_plans')
    if 'shops' in existing_tables:
        op.drop_table('shops')
    if 'hardware_products' in existing_tables:
        op.drop_table('hardware_products')
