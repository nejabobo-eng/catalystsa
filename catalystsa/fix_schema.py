#!/usr/bin/env python3
"""
Emergency schema fix: Rename 'total' → 'amount', add 'created_at'
"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import ProgrammingError

db_url = "postgresql://catalystsa_user:EPus2V6agXKaC1XV6kaQl4nXA1OaMvxs@dpg-d7e00si8qa3s73bnfodg-a.oregon-postgres.render.com/catalystsa"
engine = create_engine(db_url)

migrations = [
    # Rename total to amount
    "ALTER TABLE orders RENAME COLUMN total TO amount;",
    # Add created_at with default NOW()
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();",
]

print("🔧 Applying schema migrations...\n")

with engine.connect() as conn:
    for migration in migrations:
        try:
            conn.execute(text(migration))
            conn.commit()
            print(f"✅ {migration}")
        except ProgrammingError as e:
            error_msg = str(e)
            if "already exists" in error_msg or "does not exist" in error_msg:
                print(f"⏭️  {migration[:60]}... (already done)")
            else:
                print(f"❌ {migration[:60]}...")
                print(f"   Error: {error_msg[:100]}")

print("\n📊 Verifying schema...\n")

# Verify
inspector = inspect(engine)
columns = sorted([c['name'] for c in inspector.get_columns('orders')])
print(f"Columns in orders table ({len(columns)} total):")
for col in columns:
    print(f"  - {col}")

required = ['amount', 'created_at', 'currency', 'checkout_id', 'order_number', 'paid_at', 'delivery_fee', 'customer_email']
missing = [col for col in required if col not in columns]

print(f"\n{'✅ Schema is correct!' if not missing else f'❌ Missing columns: {missing}'}")
