from sqlalchemy import text
from catalystsa.database import engine

sql = """
ALTER TABLE products
ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS views_count INTEGER DEFAULT 0;

-- Ensure existing rows have defaults
UPDATE products SET sales_count = 0 WHERE sales_count IS NULL;
UPDATE products SET views_count = 0 WHERE views_count IS NULL;
"""


def run_migration():
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        print("✅ Migration successful: added sales_count and views_count to products")
    except Exception as e:
        # Log and continue - migration may already be applied
        print(f"❌ Migration failed or skipped: {e}")


if __name__ == "__main__":
    run_migration()
