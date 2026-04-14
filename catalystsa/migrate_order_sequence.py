#!/usr/bin/env python3
"""
Migration script to add order_sequence table
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL not set")
    exit(1)

try:
    connection = psycopg2.connect(DATABASE_URL)
    cursor = connection.cursor()
    
    print("=" * 60)
    print("DATABASE MIGRATION: Create order_sequence table")
    print("=" * 60)
    
    # Create order_sequence table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS order_sequence (
        id INTEGER PRIMARY KEY DEFAULT 1,
        last_order_number INTEGER DEFAULT 0,
        CHECK (id = 1)
    );
    """
    
    cursor.execute(create_table_sql)
    print("✅ order_sequence table created/verified")
    
    # Ensure we have exactly one row
    cursor.execute("SELECT COUNT(*) FROM order_sequence")
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute("INSERT INTO order_sequence (id, last_order_number) VALUES (1, 0)")
        print("✅ Initialized sequence row")
    else:
        print(f"✅ Sequence already initialized ({count} row(s))")
    
    connection.commit()
    
    print("\n" + "=" * 60)
    print("🎉 Migration complete!")
    print("=" * 60)
    
    cursor.close()
    connection.close()

except Exception as e:
    print(f"❌ Migration failed: {str(e)}")
    exit(1)
