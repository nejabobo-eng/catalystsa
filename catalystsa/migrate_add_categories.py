from sqlalchemy import text
from catalystsa.database import engine

sql = """
-- Create categories table if it doesn't exist
CREATE TABLE IF NOT EXISTS categories (
  id SERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  slug VARCHAR NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Add category_id to products if missing
ALTER TABLE products
ADD COLUMN IF NOT EXISTS category_id INTEGER NULL;

-- Add foreign key constraint if it doesn't exist (best-effort)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'products' AND tc.constraint_type = 'FOREIGN KEY' AND ku.column_name = 'category_id'
  ) THEN
    ALTER TABLE products
    ADD CONSTRAINT products_category_id_fkey FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL;
  END IF;
END$$;

-- Seed categories (idempotent inserts)
INSERT INTO categories (name, slug)
VALUES
('Electronics','electronics'),
('Computers & Laptops','computers-laptops'),
('Mobile Phones & Accessories','mobile-phones-accessories'),
('Clothing & Fashion','clothing-fashion'),
('Home & Kitchen','home-kitchen'),
('Bedding & Furniture','bedding-furniture'),
('Health & Beauty','health-beauty'),
('Accessories','accessories')
ON CONFLICT (slug) DO NOTHING;

"""


def run_migration():
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        print("✅ Migration successful: categories table and product.category_id added and seeded")
    except Exception as e:
        # Log and continue - migration may already be applied or run in another process
        print(f"❌ Migration failed or skipped: {e}")


if __name__ == "__main__":
    run_migration()
