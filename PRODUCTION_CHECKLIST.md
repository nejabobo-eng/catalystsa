# 🚀 CatalystSA — Production Verification Checklist

## ✅ Current System Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Backend API** | ✅ Working | Render, Python 3.14, FastAPI |
| **Database** | ✅ Fixed | PostgreSQL, schema aligned |
| **Frontend** | ✅ Working | Next.js 14.2.35, Vercel |
| **Order Creation Flow** | ✅ Deployed | Webhook → Order → Email |
| **Email System** | ✅ Deployed | SMTP configured, non-blocking |
| **Webhook Handler** | ✅ Ready | Idempotent, logging enabled |

---

## 🔧 Environment Variables (Critical)

### On Render Backend — Must Be Set:

```env
# Yoco Payment Processing
YOCO_SECRET_KEY=...

# Email System (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASS=your-app-password
ADMIN_EMAIL=your-business@gmail.com

# Frontend
FRONTEND_URL=https://catalystsa-frontend.vercel.app

# Database
DATABASE_URL=postgresql://...  (Render should auto-set)
```

### ⚠️ Gmail Setup (if using Gmail):
1. Enable 2FA on Gmail account
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use App Password as `EMAIL_PASS` (not regular password)

---

## 🎯 Pre-Launch Verification Steps

### Step 1: Confirm Webhook Connection (CRITICAL)

```bash
GET https://catalystsa.onrender.com/debug/webhook-events
```

**Expected Response:**
```json
{"total_events": 0, "events": []}
```

**If `total_events > 0`:** Webhooks are firing ✅  
**If `total_events = 0`:** Need to verify Yoco configuration

---

### Step 2: Verify Yoco Webhook URL

In **Yoco Dashboard** → Developers → Webhooks:

✅ Webhook URL **MUST BE**:
```
https://catalystsa.onrender.com/yoco/webhook
```

❌ DO NOT use:
- `localhost` (won't work from Yoco servers)
- `/yoco/webhook/` (trailing slash)
- Wrong domain
- Test vs Live environment mismatch

---

### Step 3: Test Payment Flow (Full End-to-End)

1. **Go to checkout page:**
   ```
   https://catalystsa-frontend.vercel.app/cart
   ```

2. **Fill in test customer data:**
   - Name: `Test Customer`
   - Email: `your-test-email@example.com`
   - Phone: `0712345678`
   - Address: `123 Test Street`
   - City: `Cape Town`
   - Postal Code: `8001`
   - Add any item to cart

3. **Complete test payment** (use Yoco test card if available)

4. **Wait 10 seconds** for webhook processing

5. **Verify Order Was Created:**

   ```bash
   # Check all orders
   GET https://catalystsa.onrender.com/debug/all-orders
   ```
   
   Should show `"total_orders": 1`

6. **Verify Webhook Event Was Logged:**

   ```bash
   GET https://catalystsa.onrender.com/debug/webhook-events
   ```
   
   Should show `"total_events": 1` and `"order_created": true`

7. **Verify Order Lookup Works:**

   ```bash
   GET https://catalystsa.onrender.com/public/orders/your-test-email@example.com
   ```
   
   Should return the order details

8. **Verify Email Was Sent:**
   - Check inbox for order confirmation (customer email)
   - Check `ADMIN_EMAIL` for admin notification
   - Email should contain link: `/orders?email=your-test-email@example.com`

---

### Step 4: Verify Email Functionality

**Customer Confirmation Email Contains:**
- ✅ Order number (e.g., #10001)
- ✅ Order date and time
- ✅ Total amount (R...)
- ✅ Delivery fee breakdown
- ✅ Delivery address
- ✅ **Button: "View Your Orders"** → Links to `/orders?email=X`

**Admin Notification Email Contains:**
- ✅ Customer name
- ✅ Customer email
- ✅ Phone number
- ✅ Delivery address
- ✅ Order total (R...)
- ✅ Status: "PAID - Ready to Process"

---

## 🔍 Debugging Checklist

### If webhook events = 0:
- [ ] Webhook URL registered in Yoco
- [ ] Domain is `https://catalystsa.onrender.com` (not localhost)
- [ ] Using correct environment (test vs live)
- [ ] Yoco API key (`YOCO_SECRET_KEY`) is correct
- [ ] Check Render logs for errors

### If webhook fires but order doesn't create:
- [ ] Check Render logs for exceptions
- [ ] Email in payload matches metadata
- [ ] Database columns exist (amount, created_at)
- [ ] Order number generator initialized

### If order creates but email doesn't send:
- [ ] `EMAIL_USER` and `EMAIL_PASS` configured
- [ ] `ADMIN_EMAIL` configured (or both emails will fail)
- [ ] Check Render logs for SMTP errors
- [ ] Gmail: verify App Password (not regular password)
- [ ] Note: Non-blocking means email failures don't prevent order creation

### If customer can't find order:
- [ ] Check email provided during checkout matches lookup email
- [ ] Email normalization: lowercase, trimmed
- [ ] Database has `created_at` and `amount` columns

---

## 📊 Expected Behavior After Fix

### Customer Journey:
1. Customer fills checkout form
2. Completes payment with Yoco
3. Yoco calls webhook immediately
4. Backend creates order atomically
5. Backend sends 2 emails (async, non-blocking)
6. Yoco redirects to success page
7. Customer receives order confirmation email
8. Customer clicks link → `/orders?email=their-email` → Sees order ✅

### Admin Journey:
1. Admin receives order notification email
2. Email has all customer + order details
3. Admin logs in to admin dashboard
4. Admin sees new order with status "paid"
5. Admin can update order status

---

## 🚨 Production Rules (Non-Negotiable)

✅ **DO:**
- Always return 200 OK from webhook (even on error)
- Log all errors for debugging
- Make email non-blocking
- Use idempotency (checkout_id unique)
- Normalize emails (lowercase, trim)
- Commit transactions atomically

❌ **DO NOT:**
- Return 500 errors from webhook
- Block order creation for email failure
- Hardcode emails in code
- Use localhost URLs
- Create orders from frontend (source of truth = webhook)
- Skip webhook validation

---

## 📞 Next Steps

1. **Verify environment variables are set on Render**
2. **Test full payment flow** using steps above
3. **Monitor logs** during test
4. **Fix any issues** before going live
5. **Document any custom payment logic**

---

## 🧪 Quick Test Command

After everything is configured:

```bash
# In one terminal, watch webhook events
watch curl https://catalystsa.onrender.com/debug/webhook-events

# In another terminal, watch all orders
watch curl https://catalystsa.onrender.com/debug/all-orders

# Then go trigger a test payment in browser
```

Once both show data after payment → System is live ✅
