# Production Monitoring Guide

## Side-Effect Idempotency Health Checks

### 1. Check for Stuck Orders (Missing Side Effects)

**SQL Query** (run in Render DB console):
```sql
-- Orders with missing customer emails (older than 5 minutes)
SELECT 
    order_number,
    customer_email,
    customer_email_sent,
    admin_email_sent,
    webhook_logged,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - created_at))/60 as age_minutes
FROM orders
WHERE 
    customer_email IS NOT NULL 
    AND customer_email_sent = FALSE
    AND created_at < NOW() - INTERVAL '5 minutes'
ORDER BY created_at DESC;
```

**Expected Result**: Empty (all customer emails sent within 5 minutes)

**If Results Found**: Email service may be down → check logs

---

### 2. Check Webhook Retry Behavior

**SQL Query**:
```sql
-- How many times did each checkout_id appear in webhook events?
SELECT 
    checkout_id,
    COUNT(*) as webhook_attempts,
    MIN(processed_at) as first_attempt,
    MAX(processed_at) as last_attempt,
    ARRAY_AGG(DISTINCT status ORDER BY status) as statuses
FROM webhook_events
WHERE processed_at > NOW() - INTERVAL '24 hours'
GROUP BY checkout_id
HAVING COUNT(*) > 1
ORDER BY webhook_attempts DESC;
```

**Expected Result**: Few entries (Yoco retries are rare)

**If High Count**: 
- Check webhook handler response times
- Verify 200 OK responses
- Look for exceptions in logs

---

### 3. Check Side Effect Completion Rates

**SQL Query**:
```sql
-- Side effect completion statistics (last 100 orders)
SELECT 
    COUNT(*) as total_orders,
    SUM(CASE WHEN customer_email_sent THEN 1 ELSE 0 END) as customer_emails_sent,
    SUM(CASE WHEN admin_email_sent THEN 1 ELSE 0 END) as admin_emails_sent,
    SUM(CASE WHEN webhook_logged THEN 1 ELSE 0 END) as webhooks_logged,
    ROUND(100.0 * SUM(CASE WHEN customer_email_sent THEN 1 ELSE 0 END) / COUNT(*), 2) as customer_email_rate,
    ROUND(100.0 * SUM(CASE WHEN admin_email_sent THEN 1 ELSE 0 END) / COUNT(*), 2) as admin_email_rate,
    ROUND(100.0 * SUM(CASE WHEN webhook_logged THEN 1 ELSE 0 END) / COUNT(*), 2) as webhook_log_rate
FROM (
    SELECT * FROM orders 
    WHERE created_at > NOW() - INTERVAL '24 hours'
    ORDER BY created_at DESC 
    LIMIT 100
) recent_orders;
```

**Expected Result**: 
- `customer_email_rate`: ~100% (for orders with email addresses)
- `admin_email_rate`: 100%
- `webhook_log_rate`: 100%

**If < 95%**: Investigate logs for errors

---

### 4. Render Logs - Key Patterns

**Look for these log patterns**:

#### ✅ Normal Flow (Good)
```
✅ Payment SUCCESS
   Checkout: ch_xxx
   Creating order...
✅ Created order #10123
🔄 Executing side effects...
   📝 Logging webhook event for order #10123
   ✅ Webhook event logged
   📧 Sending customer confirmation to customer@example.com
   ✅ Customer email sent
   📧 Sending admin notification
   ✅ Admin email sent
```

#### ⏭️ Webhook Retry (Good - Idempotent Skip)
```
✅ Order #10123 already exists (webhook retry - DB enforced idempotency)
🔄 Checking for missing side effects...
   ⏭️  Webhook already logged (idempotent skip)
   ⏭️  Customer email already sent (idempotent skip)
   ⏭️  Admin email already sent (idempotent skip)
```

#### 🔄 Partial Recovery (Good - Missing Effects Executed)
```
✅ Order #10123 already exists (webhook retry - DB enforced idempotency)
🔄 Checking for missing side effects...
   ⏭️  Webhook already logged (idempotent skip)
   ⏭️  Customer email already sent (idempotent skip)
   📧 Sending admin notification
   ✅ Admin email sent
```

#### ❌ Error Patterns (Investigate)
```
❌ Failed to send customer email: [error message]
```
→ Email service issue (SendGrid rate limit? API key?)

```
❌ Failed to log webhook event: [error message]
```
→ Database write issue (connection pool exhausted?)

---

### 5. Email Delivery Monitoring

**Check SendGrid Dashboard**:
1. Login to SendGrid
2. Navigate to Stats → Email Activity
3. Filter by last 24 hours

**Metrics to Watch**:
- **Delivered**: Should match order count (×2 for customer + admin)
- **Bounced**: Should be < 1%
- **Spam Reports**: Should be 0%

**Alert Conditions**:
- Delivered < 95% of sent → investigate bounces
- Spam reports > 0 → check email content

---

### 6. Database Health

**Connection Pool Status** (Render metrics):
```
Active connections: < 5
Max overflow: Should rarely hit 10
```

**If hitting max overflow frequently**:
- Increase pool_size (currently 5)
- Investigate slow queries
- Check for connection leaks

---

### 7. Performance Benchmarks

**Expected Response Times** (from Render logs):
- Webhook processing: < 500ms
- Order creation: < 100ms
- Email sending: < 2000ms (synchronous now)

**If slower**:
- Email > 3000ms → Consider async queue
- Order creation > 200ms → Check DB indexes
- Overall > 1000ms → Review connection pooling

---

## Alerting Setup (Recommended)

### Critical Alerts (Immediate Action)

1. **Order without email > 10 minutes old**
   ```sql
   SELECT COUNT(*) FROM orders 
   WHERE customer_email IS NOT NULL 
     AND customer_email_sent = FALSE
     AND created_at < NOW() - INTERVAL '10 minutes'
   ```
   → If > 0: Email system DOWN

2. **Webhook processing error rate > 5%**
   → Check Render logs for exceptions

3. **No orders in last 2 hours (during business hours)**
   → Yoco integration issue or payment gateway down

### Warning Alerts (Monitor)

1. **Side effect completion < 98%**
   → Transient errors, may resolve

2. **Webhook retry rate > 10%**
   → Check handler performance

3. **Email bounce rate > 2%**
   → Customer email quality issue

---

## Recovery Procedures

### Scenario: Email Service Down

**Symptom**: `customer_email_sent = FALSE` for multiple orders

**Recovery**:
1. Fix email service (SendGrid API key, rate limit, etc.)
2. Find affected orders:
   ```sql
   SELECT order_number, checkout_id 
   FROM orders 
   WHERE customer_email_sent = FALSE
     AND customer_email IS NOT NULL;
   ```
3. Trigger webhook retry for each:
   ```bash
   # Simulate webhook retry (requires admin endpoint)
   curl -X POST https://your-backend.onrender.com/admin/retry-webhook \
     -H "Content-Type: application/json" \
     -d '{"checkout_id": "ch_xxx"}'
   ```
   → Handler will detect `customer_email_sent = FALSE` and resend

**Prevention**: Monitor email delivery rate continuously

---

### Scenario: Database Rollback Left Flags Inconsistent

**Symptom**: Email sent but `customer_email_sent = FALSE`

**Recovery**:
1. Verify email was actually sent (check SendGrid)
2. Manually update flag:
   ```sql
   UPDATE orders 
   SET customer_email_sent = TRUE 
   WHERE order_number = 10123;
   ```

**Prevention**: This is rare (transaction atomicity usually prevents)

---

### Scenario: Webhook Flood (DDoS or Yoco Issue)

**Symptom**: 100+ webhooks for same checkout_id

**Response**:
1. Handler is idempotent → no harm done
2. Check Yoco status page
3. Monitor DB connection pool usage
4. If pool exhausted → temporarily increase pool_size

**Prevention**: Add rate limiting (future enhancement)

---

## Daily Health Check (30 seconds)

Run this checklist every morning:

1. **[ ]** Check Render logs for errors (last 24h)
2. **[ ]** Run side-effect completion query → should be ~100%
3. **[ ]** Check SendGrid delivery rate → should be > 95%
4. **[ ]** Verify latest order has all flags = True
5. **[ ]** Check webhook_events table for retry patterns

**If all green**: System is healthy ✅

**If any red**: Follow recovery procedure for that scenario

---

## Summary

**Key Metrics**:
- Side effect completion: > 98%
- Email delivery: > 95%
- Webhook processing: < 500ms
- Database connections: < 5 active

**Key Logs**:
- "✅ Customer email sent"
- "⏭️ Already sent (idempotent skip)"
- "❌ Failed to..." (investigate immediately)

**Key Queries**:
- Orders missing emails (should be 0)
- Webhook retry frequency (should be low)
- Side effect completion rates (should be ~100%)

This monitoring setup ensures you catch issues before they affect customers.
