"""
Database migration: Add missing columns to orders table
Run this once to fix schema mismatch
"""
from sqlalchemy import text
from catalystsa.database import engine

def migrate():
    with engine.connect() as connection:
        # Add missing columns if they don't exist
        sql_commands = [
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS checkout_id VARCHAR;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'ZAR';",
        ]
        
        for sql in sql_commands:
            try:
                connection.execute(text(sql))
                print(f"✅ Executed: {sql}")
            except Exception as e:
                print(f"⚠️ {sql} - {str(e)}")
        
        connection.commit()
        print("✅ Migration complete!")

if __name__ == "__main__":
    migrate()
