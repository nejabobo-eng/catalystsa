# 🔥 Webhook Troubleshooting Guide

## The Core Question

> **"Why isn't Yoco calling my webhook?"**

This accounts for 90% of "orders not being created" issues.

---

## 🎯 Diagnosis Tree

### Check 1: Is Yoco sending webhooks at all?

```bash
GET https://catalystsa.onrender.com/debug/webhook-events
```

#### Case A: `total_events > 0` ✅
→ Yoco IS calling your webhook  
→ Skip to "Webhook fires but order fails" section

#### Case B: `total_events = 0` ❌
→ Yoco is NOT calling your webhook  
→ Continue to Check 2

---

### Check 2: Verify Webhook URL in Yoco Dashboard

**In Yoco Dashboard:**
1. Login to https://dashboard.yoco.com
2. Go to **Developers** or **Settings**
3. Find **Webhooks** section
4. Look for webhook URL

**It MUST be:**
```
https://catalystsa.onrender.com/yoco/webhook
```

**CRITICAL — Do NOT use:**
- ❌ `http://` (must be HTTPS)
- ❌ `localhost:8000` (Yoco can't reach it)
- ❌ `https://catalystsa.onrender.com/yoco/webhook/` (trailing slash)
- ❌ `https://your-computer-name/...` (must be domain)
- ❌ Old/different domain

---

### Check 3: Verify Environment Variables on Render

**On Render Backend:**
1. Go to https://dashboard.render.com
2. Find your service: `catalystsa` (or similar)
3. Click **Environment**
4. Verify these are set:

```env
✅ YOCO_SECRET_KEY = your-secret-key-here
✅ EMAIL_USER = your-email@gmail.com
✅ EMAIL_PASS = your-app-password
✅ ADMIN_EMAIL = admin@yourbusiness.com
```

**If any are missing:**
- Add them now
- **Restart service** for changes to take effect

---

### Check 4: Test Backend is Reachable

From your computer:

```bash
curl https://catalystsa.onrender.com/debug/all-orders
```

**Should return:**
```json
{"total_orders": 0, "orders": []}
```

**If 404, 502, or timeout:**
- Backend is down or URL wrong
- Check Render logs
- Verify domain is correct

---

### Check 5: Verify Payment Actually Succeeds

1. Go to: `https://catalystsa-frontend.vercel.app/cart`
2. Add item to cart
3. Go to checkout
4. Fill in test customer data
5. **Try to pay** (use Yoco test card)

**Watch these:**
- ✅ Does payment complete?
- ✅ Do you see success page?
- ✅ Do you get redirect after payment?

**If payment fails in Yoco:**
- Webhook will NEVER be called
- Fix payment issue first

---

## 🔧 Common Fixes

### Fix 1: Update Webhook URL in Yoco (Most Common)

**Symptom:** `total_events = 0` after payment

**Solution:**
1. Go to Yoco Dashboard
2. Find Webhooks settings
3. **Delete old webhook** (if exists)
4. **Add new webhook:**
   - URL: `https://catalystsa.onrender.com/yoco/webhook`
   - Events: Payment Succeeded, Payment Failed
   - Save/Enable

5. **Test:** Make test payment
6. **Verify:** `curl https://catalystsa.onrender.com/debug/webhook-events`

---

### Fix 2: Restart Render Service

**Symptom:** Environment variables set but webhook still fails

**Solution:**
1. Go to Render Dashboard
2. Find your service
3. Click **Manual Restart**
4. Wait for service to redeploy

---

### Fix 3: Check Render Logs for Errors

**Symptom:** Webhook fails with no clear reason

**Solution:**
1. Go to Render Dashboard
2. Click your service
3. Go to **Logs**
4. Look for errors after payment
5. Common errors:
   - `YOCO_SECRET_KEY not configured` → Add to environment
   - `column ... does not exist` → DB schema issue
   - `email configuration error` → Gmail setup issue

---

### Fix 4: Verify Gmail App Password (If Using Gmail)

**Symptom:** Email fails to send

**Solution:**
1. Go to https://myaccount.google.com/apppasswords
2. Select **Mail** and **Windows Computer**
3. Generate password (16 characters)
4. Copy exact password
5. Set as `EMAIL_PASS` on Render
6. **Important:** Use App Password, NOT regular Gmail password

---

## 🧪 Full Debug Flow (Do This In Order)

```bash
# Step 1: Check if backend is running
curl https://catalystsa.onrender.com/debug/all-orders

# Step 2: Check if any webhooks have fired
curl https://catalystsa.onrender.com/debug/webhook-events

# Step 3: If webhooks=0, check your Yoco dashboard
# (Go to dashboard.yoco.com → Developers → Webhooks)
# Verify URL is: https://catalystsa.onrender.com/yoco/webhook

# Step 4: Make a test payment
# Go to: https://catalystsa-frontend.vercel.app/cart
# Complete checkout

# Step 5: Check webhook again (wait 5-10 seconds)
curl https://catalystsa.onrender.com/debug/webhook-events

# Step 6: If webhooks>0, check orders
curl https://catalystsa.onrender.com/debug/all-orders

# Step 7: If orders>0, check email
# Search inbox for confirmation email
```

---

## 🚨 Emergency Checklist

If NOTHING is working:

- [ ] Is backend running? (Check Render logs)
- [ ] Is database running? (Try `/debug/all-orders`)
- [ ] Is Yoco webhook URL set? (Check Yoco dashboard)
- [ ] Did payment actually complete? (Check Yoco transaction log)
- [ ] Are environment variables set? (Check Render settings)
- [ ] Did you restart Render after changing env vars? (Manual restart)
- [ ] Are email credentials correct? (Test SMTP separately)

---

## 📞 What To Tell Support

If you need help, provide:

1. **Webhook events count:**
   ```
   curl https://catalystsa.onrender.com/debug/webhook-events
   ```

2. **Orders in database:**
   ```
   curl https://catalystsa.onrender.com/debug/all-orders
   ```

3. **Yoco webhook URL** (from dashboard)

4. **Render logs** (last 50 lines from /yoco/webhook endpoint)

5. **Did payment complete?** (yes/no)

---

## 💡 Key Insights

**Rule 1:** Webhook = Source of Truth
- Orders ONLY created when Yoco calls webhook
- Frontend can't create orders (would bypass payment)

**Rule 2:** 200 OK Always
- Even if error, return 200 to Yoco
- Yoco retries on errors

**Rule 3:** Email Failures Don't Block Order**
- Order created FIRST
- Email sent SECOND (async)
- Email fails → order still exists ✅

---

## 🎯 Expected Timeline After Fix

After you verify webhook URL in Yoco:

1. **Payment completes** → 2 seconds
2. **Webhook received** → 1-3 seconds  
3. **Order created** → 0.1 seconds
4. **Email sent** → 2-5 seconds
5. **Total time** → ~10 seconds

Check `/debug/webhook-events` after 10 seconds.
