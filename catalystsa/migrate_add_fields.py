#!/usr/bin/env python3
"""
Migration script to add new fields to orders table:
- order_number (Integer, unique)
- city (String)
- postal_code (String)
- delivery_fee (Integer, in cents)
- items (String, JSON)
"""

import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL not set")
    exit(1)

# Parse connection string
try:
    connection = psycopg2.connect(DATABASE_URL)
    cursor = connection.cursor()
    
    print("=" * 60)
    print("DATABASE MIGRATION: Add Order Fields")
    print("=" * 60)
    print(f"📦 Connecting to database...")
    print(f"Connection successful! ✅")
    
    # List of migrations to run
    migrations = [
        ("order_number", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_number INTEGER UNIQUE;"),
        ("city", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS city VARCHAR;"),
        ("postal_code", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS postal_code VARCHAR;"),
        ("delivery_fee", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_fee INTEGER;"),
        ("items", "ALTER TABLE orders ADD COLUMN IF NOT EXISTS items TEXT;"),
    ]
    
    print("\n🔄 Running migrations...")
    for name, sql in migrations:
        try:
            cursor.execute(sql)
            print(f"✅ {name}: Column added/verified")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"✅ {name}: Column already exists")
            else:
                print(f"❌ {name}: {str(e)}")
                connection.rollback()
                raise
    
    connection.commit()
    
    print("\n" + "=" * 60)
    print("🎉 Migration complete!")
    print("=" * 60)
    
    # Verify columns
    print("\n📋 Verifying columns...")
    cursor.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'orders'
        ORDER BY ordinal_position;
    """)
    
    columns = cursor.fetchall()
    for col in columns:
        nullable = "NULL" if col[2] == "YES" else "NOT NULL"
        print(f"  - {col[0]}: {col[1]} ({nullable})")
    
    cursor.close()
    connection.close()
    
    print("\n✅ All verified!")

except Exception as e:
    print(f"❌ Migration failed: {str(e)}")
    exit(1)
