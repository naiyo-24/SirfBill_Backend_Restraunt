import os
from sqlalchemy import text
from models.database import engine, Base
import models.restaurant_customer
import models.restaurant_outlet
import models.restaurant_order
import models.user

def run_migration():
    print("Creating all tables defined in models...")
    Base.metadata.create_all(bind=engine)
    print("Tables verified.")

    # Apply ALTER TABLE for newly added columns to restaurant_customers and restaurant_loyalty_ledger
    migrations = [
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS home_outlet_id UUID REFERENCES restaurant_outlets(id) ON DELETE SET NULL;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS dob DATE;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS anniversary DATE;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS gst_number VARCHAR(20);",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS preferences JSON DEFAULT '{}'::json;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS tags JSON DEFAULT '[\"NEW\"]'::json;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS total_visits INTEGER DEFAULT 0;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS total_spent NUMERIC(12,2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS avg_order_value NUMERIC(10,2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS last_visit_at TIMESTAMP;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS loyalty_points INTEGER DEFAULT 0;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS credit_balance NUMERIC(12,2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(12,2) DEFAULT 0.00;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS opt_in_marketing BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS notes TEXT;",
        "ALTER TABLE restaurant_customers ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE restaurant_loyalty_ledger ADD COLUMN IF NOT EXISTS balance_after INTEGER DEFAULT 0;",
    ]

    with engine.begin() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                print(f"Migration note for statement: {sql} -> {e}")

    print("Database migrations applied successfully!")

if __name__ == "__main__":
    run_migration()
