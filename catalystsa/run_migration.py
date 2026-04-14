#!/usr/bin/env python3
"""
Database migration runner with verbose output
Run: python run_migration.py
"""
import os
import sys
from sqlalchemy import text, create_engine

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL environment variable not set!")
    print("Set it in your .env file or Render environment")
    sys.exit(1)

print(f"📦 Connecting to database...")
print(f"   URL: {DATABASE_URL[:50]}...")

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    
    # Test connection
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        print("✅ Database connection successful!\n")
    
    # Run migrations
    print("🔄 Running migrations...\n")
    sql_commands = [
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS checkout_id VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'ZAR';",
    ]
    
    with engine.connect() as connection:
        for sql in sql_commands:
            try:
                connection.execute(text(sql))
                connection.commit()
                print(f"✅ {sql}")
            except Exception as e:
                print(f"⚠️  {sql}")
                print(f"    Error: {str(e)}\n")
    
    print("\n🎉 Migration complete!")
    print("\n✨ Your database is now ready for orders!")
    print("   Test: curl https://catalystsa.onrender.com/yoco/orders")
    
except Exception as e:
    print(f"❌ FATAL ERROR: {str(e)}")
    sys.exit(1)
