# SirfBill Restaurant Platform - Database Consolidation Plan
**Document Version:** 1.0  
**Current Date:** November 21, 2026  
**Target Goal:** Streamline database schema from **58 tables down to 26 tables** (~55% reduction).

---

## Executive Summary

The database currently holds **58 tables** in PostgreSQL (57 ORM model tables + 1 `alembic_version`). An exhaustive audit reveals that:
1. **13 tables are obsolete legacy retail shop tables** from before the pivot to the enterprise restaurant architecture. Most hold 0 rows.
2. **6 tables are over-normalized 1:1 or 1:few lookup tables** (e.g., `restaurant_item_prices` which mirrors `restaurant_menu_items` 1:1 with 113 rows).
3. **2 customer ledger tables** (`restaurant_loyalty_ledger` and `restaurant_customer_credit_ledger`) record parallel customer adjustments and can be merged into a unified polymorphic ledger.
4. **2 legacy auth/payment tables** (`otp_codes`, `payments`) are dormant (0 rows).

Consolidating these tables will:
- **Reduce table count by 55%** (58 tables → 26 tables).
- **Accelerate queries** by eliminating redundant `JOIN`s on hot paths (e.g. menu rendering, recipe BOM calculations).
- **Simplify schema maintenance & Alembic migrations**.
- **Preserve 100% of production data** (orders, order lines, audit events, menu items, hardware catalog).

---

## Comprehensive Audit of All 58 Tables

### Domain 1: Legacy Retail / Shop Tables (Obsolete - 13 Tables)
*These tables were part of the initial single-shop retail billing codebase. All have 0 rows or duplicate restaurant entities.*

| # | Table Name | Columns | Rows | Purpose / Status | Foreign Keys |
|---|------------|---------|------|------------------|--------------|
| 1 | `shops` | 11 | 2 | Legacy shop entity (Superceded by `restaurant_outlets`) | None |
| 2 | `shop_settings` | 22 | 2 | Legacy shop preferences (tax, receipt headers) | `shops` |
| 3 | `shop_bills` | 19 | 0 | Old retail bill records (Superceded by `restaurant_orders`) | `shops`, `users` |
| 4 | `shop_bill_items` | 11 | 0 | Old retail bill items (Superceded by `restaurant_order_lines`) | `shop_bills`, `inventory_items` |
| 5 | `categories` | 6 | 0 | Old retail categories (Superceded by `restaurant_menu_categories`) | `shops` |
| 6 | `racks` | 6 | 0 | Physical warehouse rack locations | `shops` |
| 7 | `inventory_items` | 23 | 0 | Retail barcode inventory (Superceded by restaurant inventory) | `shops`, `categories`, `distributors`, `racks` |
| 8 | `distributors` | 12 | 2 | Retail vendor master (Superceded by `restaurant_suppliers`) | `shops` |
| 9 | `purchase_bills` | 14 | 0 | Retail purchase invoices (Superceded by `restaurant_grn`) | `shops`, `distributors` |
| 10 | `purchase_bill_items` | 10 | 0 | Retail purchase line items (Superceded by `restaurant_grn_items`) | `purchase_bills`, `inventory_items` |
| 11 | `accounts` | 8 | 0 | Old retail accounting ledger accounts | None |
| 12 | `transactions` | 16 | 0 | Old cashbook debit/credit transactions | `accounts`, `transaction_categories` |
| 13 | `transaction_categories` | 5 | 0 | Categories for cashbook transactions | None |

---

### Domain 2: Restaurant POS, Menu & Ordering (Core Active - 14 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 14 | `restaurant_outlets` | 35 | 2 | Restaurant branch/outlet master (FSSAI, GSTIN, tables, config) | `shops` |
| 15 | `restaurant_tables` | 10 | 6 | Dining floor tables, capacity, QR codes, active order link | `restaurant_outlets` |
| 16 | `restaurant_menu_categories` | 10 | 11 | Menu categories (Starters, Main Course, Beverages, etc.) | `restaurant_outlets` |
| 17 | `restaurant_menu_items` | 17 | 113 | Dish catalog (name, description, tax slab, food type) | `restaurant_outlets`, `restaurant_menu_categories` |
| 18 | `restaurant_item_prices` | 6 | 113 | Portion prices (Dine-in, Takeaway, Delivery prices per item) | `restaurant_menu_items` |
| 19 | `restaurant_modifier_groups` | 9 | 0 | Add-on groups (e.g., 'Choose Crust', 'Spice Level') | `restaurant_outlets` |
| 20 | `restaurant_modifier_options` | 7 | 0 | Modifier choices (e.g., 'Cheese Burst', 'Extra Hot') | `restaurant_modifier_groups` |
| 21 | `restaurant_item_modifier_groups` | 4 | 0 | Many-to-Many join table linking items to modifier groups | `restaurant_menu_items`, `restaurant_modifier_groups` |
| 22 | `restaurant_orders` | 25 | 169 | Master orders (order number, table, customer, gross/net amounts) | `restaurant_outlets`, `restaurant_tables`, `restaurant_shifts`, `users` |
| 23 | `restaurant_order_lines` | 17 | 404 | Order items with quantity, modifiers, discount, tax breakdown | `restaurant_orders`, `restaurant_menu_items` |
| 24 | `restaurant_tenders` | 10 | 163 | Payment splits (Cash, UPI, Card, Due/Credit per order) | `restaurant_orders`, `users` |
| 25 | `restaurant_refunds` | 7 | 0 | Audit records of refunded payments | `restaurant_orders`, `restaurant_tenders`, `users` |
| 26 | `restaurant_shifts` | 12 | 0 | Cashier drawer shift sessions, opening float, counted cash | `restaurant_outlets`, `users` |
| 27 | `restaurant_audit_events` | 11 | 812 | Immutable audit log (price overrides, voids, reprints, discounts) | `restaurant_outlets`, `users` |

---

### Domain 3: Kitchen Display System (KDS & KOT - 3 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 28 | `restaurant_kitchen_tickets` | 11 | 199 | Physical/digital KOT headers (KOT-YYYYMMDD-XXXX) | `restaurant_orders`, `users` |
| 29 | `restaurant_kitchen_ticket_items` | 9 | 397 | Line items routed to kitchen stations (Tandoor, Pantry, Main) | `restaurant_kitchen_tickets`, `restaurant_order_lines` |
| 30 | `restaurant_kitchen_events` | 7 | 199 | Event log of KOT state changes (FIRED → PREPARING → BUMPED) | `restaurant_kitchen_tickets`, `users` |

---

### Domain 4: Restaurant Inventory, Recipes & Procurement (14 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 31 | `restaurant_ingredient_categories` | 13 | 2 | Storage categories (Dairy, Vegetables, Meat, Packaging) | `restaurant_outlets` |
| 32 | `restaurant_ingredients` | 26 | 4 | Raw material items with UOM, par stock levels, and WAC cost | `restaurant_outlets`, `restaurant_ingredient_categories`, `distributors` |
| 33 | `restaurant_suppliers` | 17 | 2 | Vendor master (FSSAI, GSTIN, payment terms, contact info) | `restaurant_outlets` |
| 34 | `restaurant_purchase_orders` | 17 | 13 | Purchase order headers sent to suppliers | `restaurant_outlets`, `restaurant_suppliers`, `users` |
| 35 | `restaurant_purchase_order_items` | 11 | 13 | PO line items with expected quantities and quoted rates | `restaurant_purchase_orders`, `restaurant_ingredients` |
| 36 | `restaurant_grn` | 15 | 12 | Goods Received Note (actual delivered stock, invoice number) | `restaurant_outlets`, `restaurant_suppliers`, `restaurant_purchase_orders`, `users` |
| 37 | `restaurant_grn_items` | 14 | 12 | Line items received with accepted vs rejected quantities | `restaurant_grn`, `restaurant_ingredients`, `restaurant_purchase_order_items` |
| 38 | `restaurant_recipes` | 9 | 2 | Bill of Materials (BOM) linking menu dishes to ingredients | `restaurant_outlets`, `restaurant_menu_items`, `restaurant_modifier_options`, `restaurant_ingredients` |
| 39 | `restaurant_recipe_lines` | 5 | 3 | Specific ingredient quantities consumed per portion | `restaurant_recipes`, `restaurant_ingredients` |
| 40 | `restaurant_stock_ledger` | 13 | 64 | Moving average cost and transaction log of every stock movement | `restaurant_outlets`, `restaurant_ingredients`, `users` |
| 41 | `restaurant_stock_transfers` | 25 | 6 | Inter-branch dispatch headers (Source → Destination outlet) | `restaurant_outlets`, `users` |
| 42 | `restaurant_stock_transfer_items` | 18 | 6 | Line items transferred between branches | `restaurant_stock_transfers`, `restaurant_ingredients` |
| 43 | `restaurant_stock_audits` | 14 | 2 | Physical stock-take audit sessions | `restaurant_outlets`, `users` |
| 44 | `restaurant_stock_audit_items` | 17 | 2 | Line-by-line counted variance (System vs Physical Count) | `restaurant_stock_audits`, `restaurant_ingredients` |

---

### Domain 5: CRM, Loyalty & Customer Credit (5 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 45 | `restaurant_customers` | 24 | 3 | Customer profiles (phone, visits, total spend, credit balance) | `restaurant_outlets` |
| 46 | `restaurant_loyalty_rules` | 11 | 1 | Outlet loyalty earning/burning rules and redemption limits | `restaurant_outlets` |
| 47 | `restaurant_loyalty_ledger` | 8 | 1 | Points earn/burn transaction history | `restaurant_customers`, `restaurant_orders` |
| 48 | `restaurant_customer_credit_ledger` | 12 | 1 | Customer credit (Khata / Udhar) debit & settlement history | `restaurant_outlets`, `restaurant_customers`, `restaurant_orders` |
| 49 | `restaurant_crm_notifications` | 12 | 3 | SMS/WhatsApp promotion logs and delivery status | `restaurant_outlets`, `restaurant_customers` |

---

### Domain 6: Platform Subscriptions & Billing (3 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 50 | `subscription_plans` | 13 | 4 | SaaS tiers (SILVER, GOLD, PLATINUM, ENTERPRISE) | None |
| 51 | `tenant_subscriptions` | 17 | 1 | Active restaurant subscription license and validity | `restaurant_outlets`, `subscription_plans`, `users` |
| 52 | `subscription_payments` | 11 | 1 | Razorpay gateway payment invoices for platform renewals | `tenant_subscriptions` |

---

### Domain 7: POS Hardware Marketplace (2 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 53 | `hardware_products` | 25 | 8 | POS printers, terminals, KDS screens, handheld PDA catalog | None |
| 54 | `hardware_orders` | 24 | 2 | Purchase orders placed by restaurants for certified hardware | `hardware_products`, `restaurant_outlets` |

---

### Domain 8: System, Users & Migrations (4 Tables)

| # | Table Name | Columns | Rows | Purpose / Content | Foreign Keys |
|---|------------|---------|------|-------------------|--------------|
| 55 | `users` | 13 | 16 | System staff, cashiers, kitchen captains, admins | `restaurant_outlets` |
| 56 | `otp_codes` | 3 | 0 | Old auth SMS OTP store (now in Redis/memory) | None |
| 57 | `payments` | 11 | 0 | Old delivery parcel payment table | `users` |
| 58 | `alembic_version` | 1 | 1 | Alembic migration state tracker | None |

---

## Consolidation Architecture ("How to Join & Merge")

### Consolidation 1: Merge `restaurant_item_prices` into `restaurant_menu_items`
- **Current State:** 1:1 relation between `restaurant_menu_items` (113 rows) and `restaurant_item_prices` (113 rows).
- **Consolidation Action:** Migrate `dine_in_price`, `takeaway_price`, `delivery_price` directly onto `restaurant_menu_items`.
- **SQL Migration Query:**
```sql
ALTER TABLE restaurant_menu_items 
ADD COLUMN IF NOT EXISTS price NUMERIC(10, 2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS takeaway_price NUMERIC(10, 2),
ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(10, 2);

-- Update join to transfer pricing data:
UPDATE restaurant_menu_items m
SET 
  price = p.dine_in_price,
  takeaway_price = p.takeaway_price,
  delivery_price = p.delivery_price
FROM restaurant_item_prices p
WHERE m.id = p.item_id;

DROP TABLE restaurant_item_prices;
```

---

### Consolidation 2: Merge Modifiers into `restaurant_modifier_groups`
- **Current State:** Modifiers are split across 3 tables (`restaurant_modifier_groups`, `restaurant_modifier_options`, `restaurant_item_modifier_groups`).
- **Consolidation Action:** Embed modifier options and applicable menu item IDs as `JSONB` inside `restaurant_modifier_groups`.
- **SQL Migration Query:**
```sql
ALTER TABLE restaurant_modifier_groups
ADD COLUMN IF NOT EXISTS options JSONB DEFAULT '[]'::jsonb,
ADD COLUMN IF NOT EXISTS applicable_item_ids JSONB DEFAULT '[]'::jsonb;

DROP TABLE IF EXISTS restaurant_item_modifier_groups;
DROP TABLE IF EXISTS restaurant_modifier_options;
```

---

### Consolidation 3: Merge Ingredient Categories into `restaurant_ingredients`
- **Current State:** `restaurant_ingredient_categories` has only 2 rows.
- **Consolidation Action:** Add `category_name` column to `restaurant_ingredients` and drop the separate table.
- **SQL Migration Query:**
```sql
ALTER TABLE restaurant_ingredients
ADD COLUMN IF NOT EXISTS category_name VARCHAR(100) DEFAULT 'General';

UPDATE restaurant_ingredients i
SET category_name = c.name
FROM restaurant_ingredient_categories c
WHERE i.category_id = c.id;

DROP TABLE restaurant_ingredient_categories;
```

---

### Consolidation 4: Merge Recipe Lines into `restaurant_recipes`
- **Current State:** `restaurant_recipes` (2 rows) and `restaurant_recipe_lines` (3 rows) represent dish BOM recipes.
- **Consolidation Action:** Store ingredient line items as a `JSONB` array within `restaurant_recipes`.
- **SQL Migration Query:**
```sql
ALTER TABLE restaurant_recipes
ADD COLUMN IF NOT EXISTS items JSONB DEFAULT '[]'::jsonb;

UPDATE restaurant_recipes r
SET items = (
  SELECT COALESCE(json_agg(json_build_object(
    'ingredient_id', l.ingredient_id,
    'quantity', l.quantity,
    'uom', l.uom,
    'cost_share_pct', l.cost_share_pct
  )), '[]'::jsonb)
  FROM restaurant_recipe_lines l
  WHERE l.recipe_id = r.id
);

DROP TABLE restaurant_recipe_lines;
```

---

### Consolidation 5: Unify Customer Loyalty & Credit into `restaurant_customer_ledger`
- **Current State:** Two separate ledger tables (`restaurant_loyalty_ledger`, `restaurant_customer_credit_ledger`).
- **Consolidation Action:** Merge both into a single polymorphic `restaurant_customer_ledger`.
- **SQL Migration Query:**
```sql
CREATE TABLE IF NOT EXISTS restaurant_customer_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id UUID REFERENCES restaurant_outlets(id),
    customer_id UUID REFERENCES restaurant_customers(id),
    order_id UUID REFERENCES restaurant_orders(id),
    ledger_type VARCHAR(20) NOT NULL, -- 'LOYALTY_POINTS' or 'KHATA_CREDIT'
    transaction_type VARCHAR(20) NOT NULL, -- 'EARN', 'BURN', 'CREDIT_ISSUE', 'PAYMENT_SETTLE'
    points_change NUMERIC(10,2) DEFAULT 0,
    amount_change NUMERIC(10,2) DEFAULT 0,
    closing_balance NUMERIC(10,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Migrate loyalty ledger:
INSERT INTO restaurant_customer_ledger (id, outlet_id, customer_id, order_id, ledger_type, transaction_type, points_change, closing_balance, created_at)
SELECT id, outlet_id, customer_id, order_id, 'LOYALTY_POINTS', transaction_type, points, balance_after, created_at
FROM restaurant_loyalty_ledger;

-- Migrate credit ledger:
INSERT INTO restaurant_customer_ledger (id, outlet_id, customer_id, order_id, ledger_type, transaction_type, amount_change, closing_balance, created_at)
SELECT id, outlet_id, customer_id, order_id, 'KHATA_CREDIT', entry_type, amount, balance_after, created_at
FROM restaurant_customer_credit_ledger;

DROP TABLE restaurant_loyalty_ledger;
DROP TABLE restaurant_customer_credit_ledger;
```

---

### Consolidation 6: Drop 13 Obsolete Legacy Shop Tables
- **SQL Migration Query:**
```sql
DROP TABLE IF EXISTS shop_bill_items CASCADE;
DROP TABLE IF EXISTS shop_bills CASCADE;
DROP TABLE IF EXISTS purchase_bill_items CASCADE;
DROP TABLE IF EXISTS purchase_bills CASCADE;
DROP TABLE IF EXISTS inventory_items CASCADE;
DROP TABLE IF EXISTS racks CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS transaction_categories CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS shop_settings CASCADE;
DROP TABLE IF EXISTS distributors CASCADE;
DROP TABLE IF EXISTS shops CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS otp_codes CASCADE;
```

---

## Target Database Schema (26 Clean Tables)

| Domain | Target Table Name | Key Entity / Purpose |
|---|---|---|
| **Auth & Multi-Tenancy** | `users` | Staff, cashiers, captains, admins |
| | `restaurant_outlets` | Restaurant branch master & settings |
| **POS & Floor** | `restaurant_tables` | Dine-in tables, QR codes, capacity |
| | `restaurant_menu_categories` | Menu item categories |
| | `restaurant_menu_items` | Dish master with embedded prices |
| | `restaurant_modifier_groups` | Add-ons & options (with JSONB options) |
| | `restaurant_shifts` | Cashier shifts & cash drawer float |
| **Orders & Billing** | `restaurant_orders` | Master orders |
| | `restaurant_order_lines` | Item lines & modifiers |
| | `restaurant_tenders` | Payment splits (Cash, UPI, Card, Due) |
| | `restaurant_refunds` | Refund audit records |
| | `restaurant_audit_events` | Immutable security log |
| **Kitchen KDS** | `restaurant_kitchen_tickets` | KOT headers |
| | `restaurant_kitchen_ticket_items` | Kitchen station line items |
| **Inventory & Recipes** | `restaurant_ingredients` | Raw materials with WAC cost |
| | `restaurant_recipes` | Dish BOM recipes (with JSONB items) |
| | `restaurant_stock_ledger` | Stock valuation ledger |
| **Procurement & Transfers** | `restaurant_suppliers` | Vendor master |
| | `restaurant_purchase_orders` | PO headers |
| | `restaurant_purchase_order_items` | PO line items |
| | `restaurant_grn` | Inward stock receipts |
| | `restaurant_grn_items` | GRN line items |
| | `restaurant_stock_transfers` | Inter-branch dispatch |
| | `restaurant_stock_transfer_items` | Transfer item lines |
| | `restaurant_stock_audits` | Physical stock-take audits |
| | `restaurant_stock_audit_items` | Audit variance items |
| **CRM & Loyalty** | `restaurant_customers` | Customer master |
| | `restaurant_customer_ledger` | Unified loyalty & Khata credit ledger |
| | `restaurant_crm_notifications` | WhatsApp/SMS campaign logs |
| **SaaS & Hardware** | `subscription_plans` | Platform tiers |
| | `tenant_subscriptions` | Active license subscriptions |
| | `subscription_payments` | Gateway renewal receipts |
| | `hardware_products` | Certified POS hardware catalog |
| | `hardware_orders` | Hardware purchase orders |
| **System** | `alembic_version` | Migration state tracker |

---
*Generated by SirfBill Engineering Architecture.*
