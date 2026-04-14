# Database migration script for Windows PowerShell
$DatabaseURL = "postgresql://catalystsa_user:EPus2V6agXKaC1XV6kaQl4nXA1OaMvxs@dpg-d7e00si8qa3s73bnfodg-a.oregon-postgres.render.com/catalystsa"

$SqlCommands = @"
ALTER TABLE orders ADD COLUMN IF NOT EXISTS checkout_id VARCHAR;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email VARCHAR;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'ZAR';
"@

Write-Host "🔄 Running database migration..." -ForegroundColor Cyan
Write-Host ""

# Try using psql
try {
    $SqlCommands | psql $DatabaseURL
    Write-Host ""
    Write-Host "✅ Migration complete!" -ForegroundColor Green
    Write-Host "🎉 Your database is now ready for orders!" -ForegroundColor Green
}
catch {
    Write-Host "❌ Error: psql not found or connection failed" -ForegroundColor Red
    Write-Host "Please install PostgreSQL client tools or use Render's web dashboard" -ForegroundColor Yellow
}
