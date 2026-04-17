# Clean Stripe-Style Webhook Architecture

## Core Principle

> **The database guarantees correctness of money state.**  
> **Everything else is best-effort.**

This is not a compromise—it's **intentional architectural clarity**.

---

## What This System Guarantees

### 🟢 Absolute Guarantees (Database-Enforced)

| Guarantee | Mechanism | Why It Can't Fail |
|-----------|-----------|-------------------|
| **One order per payment** | `checkout_id UNIQUE constraint` | PostgreSQL enforces uniqueness |
| **No lost payments** | Webhook retry + idempotent handler | Yoco retries until 200 OK |
| **Order status reflects truth** | `status = "paid"` set atomically | Transaction commits or rolls back |
| **No race conditions** | Database serializes concurrent inserts | ACID guarantees |

### 🟡 Best-Effort (Accepted Trade-offs)

| Concern | Current Behavior | Why Acceptable |
|---------|------------------|----------------|
| **Duplicate emails** | May occur on rare webhook retry | Email ≠ money, low impact |
| **Missing email** | Logged as error, no auto-retry | Can be manually resent |
| **Audit log duplicates** | May occur on retry | Debugging only, not business logic |

---

## Architecture Layers

### Layer 1: Business Domain (Order Model)

**Purpose**: Single source of truth for payment state

```python
class Order(Base):
    checkout_id = Column(String, unique=True, index=True)  # Idempotency key
    status = Column(String)  # Business state: pending | paid | failed
    amount = Column(Integer)
    customer_email = Column(String)
    # ... customer data ...
```

**What's NOT here**:
- ❌ No `email_sent` flags
- ❌ No `webhook_processed` flags
- ❌ No infrastructure state

**Why**: Domain models should represent business entities, not execution state.

---

### Layer 2: Event Handler (Webhook Route)

**Purpose**: Ensure order exists and reflects payment state

```python
@router.post("/webhook")
async def yoco_webhook(request, db):
    checkout_id = payload["data"]["id"]

    # Check if order exists
    order = db.query(Order).filter(Order.checkout_id == checkout_id).first()

    if order:
        # Webhook retry - ensure status is correct
        order.status = "paid"
        db.commit()
    else:
        # New payment - create order
        order = Order(checkout_id=checkout_id, status="paid", ...)
        db.add(order)
        db.commit()

    # Side effects (best effort)
    send_emails(order)

    return {"status": "received"}
```

**Key insight**: Check-then-create pattern is safe because:
1. Database UNIQUE constraint prevents duplicates
2. Race condition just means another process created the order (correct outcome)
3. Status update is idempotent

---

### Layer 3: Side Effects (Email Service)

**Purpose**: Best-effort notifications

```python
def send_emails_best_effort(order):
    try:
        send_customer_email(order)
    except Exception:
        logger.error("Email failed")  # Logged, not blocking
```

**Why "best effort"**:
- Email failure doesn't invalidate payment
- Retry mechanisms add complexity without proportional value
- Manual resend is acceptable for rare failures

---

## Idempotency Model

### What Makes This "Stripe-Style"

**Stripe's PaymentIntent** works exactly like this:

1. **Idempotency key** = `checkout_id` (our case) or explicit key (Stripe API)
2. **Database constraint** enforces uniqueness
3. **Webhooks are events**, not commands
4. **Side effects are retryable**, not part of correctness model

### What We Explicitly Don't Do

**❌ Event Sourcing Inside Domain Model**
```python
# DON'T do this:
class Order(Base):
    email_sent = Column(Boolean)  # ❌ Infrastructure state in domain
    webhook_processed = Column(Boolean)  # ❌ Execution state in domain
```

**Why not**: This couples business logic with infrastructure concerns, making the system harder to reason about.

**✅ Clean Separation**
```python
# DO this:
class Order(Base):
    status = Column(String)  # ✅ Business state only
```

Side effects tracked elsewhere (audit logs) or accepted as best-effort.

---

## Failure Scenarios

### Scenario 1: Normal Payment ✅

```
1. Payment succeeds at Yoco
2. Webhook arrives
3. Order created (checkout_id = ch_abc123)
4. Emails sent
5. Return 200 OK
```

**Result**: Order exists, customer notified.

---

### Scenario 2: Webhook Retry (Yoco Didn't Receive 200) ✅

```
1. Original webhook arrives
2. Order created
3. Network fails before Yoco receives 200
4. Yoco retries webhook
5. Handler checks: order exists? Yes.
6. Update status = "paid" (idempotent)
7. Send emails (may duplicate)
8. Return 200 OK
```

**Result**: 
- ✅ Order correct (status = paid)
- ⚠️ Customer may receive 2 emails (rare, acceptable)

---

### Scenario 3: Concurrent Webhooks (Race Condition) ✅

```
Process A: Create order with checkout_id = ch_abc123
Process B: Create order with checkout_id = ch_abc123 (at same time)

Database:
- One succeeds (A)
- One gets IntegrityError (B)

Handler (Process B):
- Catches IntegrityError
- Queries for existing order
- Updates status = "paid"
- Returns success
```

**Result**: Database prevents duplicate, both processes return success (correct).

---

### Scenario 4: Email Service Down ⚠️

```
1. Webhook arrives
2. Order created ✅
3. Email service fails ❌
4. Error logged
5. Return 200 OK to Yoco (prevents retry storm)
```

**Result**:
- ✅ Payment recorded (money is safe)
- ❌ Customer not notified (acceptable, can be manually resolved)

**Why this is OK**:
- Payment correctness > notification delivery
- Email service outage is external system failure
- Webhook retry wouldn't help if service is down
- Manual resend is acceptable for rare outages

---

## What We Removed (and Why)

### Removed: Side-Effect Tracking Flags

**Before**:
```python
class Order(Base):
    customer_email_sent = Column(Boolean, default=False)
    admin_email_sent = Column(Boolean, default=False)
    webhook_logged = Column(Boolean, default=False)
```

**After**:
```python
class Order(Base):
    # Removed - not part of business domain
```

**Why**:
1. **Domain pollution**: Email delivery is infrastructure, not business state
2. **Complexity**: State machine in domain model is hard to reason about
3. **Diminishing returns**: Solving rare email duplicates adds significant complexity
4. **Better alternatives**: If email deduplication becomes critical, use:
   - Dedicated `EmailLog` table (separate concern)
   - Message queue with idempotency keys
   - External service (SendGrid) deduplication

---

### Removed: `execute_side_effects()` Function

**Before**:
```python
def execute_side_effects(order, payload, db):
    if not order.webhook_logged:
        log_webhook_event(...)
        order.webhook_logged = True
        db.commit()

    if not order.customer_email_sent:
        send_email(...)
        order.customer_email_sent = True
        db.commit()
    # ...
```

**After**:
```python
def send_emails_best_effort(order):
    try:
        send_customer_email(order)
    except:
        logger.error("Failed")
```

**Why**:
- **Simpler**: Direct function calls, easy to read
- **Honest**: Name says "best effort" (sets expectations)
- **No hidden state**: No flags to track, no DB commits for emails

---

## Comparison to Over-Engineered Alternative

### ❌ Over-Engineered (What We Avoided)

```python
# Complex state machine
if not order.email_sent:
    send_email()
    order.email_sent = True
    db.commit()

if not order.webhook_logged:
    log_event()
    order.webhook_logged = True
    db.commit()

# Multiple commits per request
# State spread across domain model
# Hard to debug
```

**Problems**:
- 3+ database commits per webhook
- Domain model knows about infrastructure
- Harder to test
- More edge cases to handle

### ✅ Clean (Current Implementation)

```python
# Simple, direct
order = get_or_create_order(checkout_id)
order.status = "paid"
db.commit()

send_emails_best_effort(order)
```

**Benefits**:
- 1 database commit (order state)
- Domain model is clean
- Easy to test
- Obvious what happens

---

## Production Monitoring

### Critical Metrics (Alert Immediately)

1. **Orders without payment**: Should be 0
   ```sql
   SELECT COUNT(*) FROM orders WHERE status = 'pending' AND created_at < NOW() - INTERVAL '1 hour'
   ```

2. **Webhook processing errors**: Should be < 1%
   ```sql
   SELECT COUNT(*) FROM webhook_events WHERE status = 'failed' AND processed_at > NOW() - INTERVAL '24 hours'
   ```

### Best-Effort Metrics (Monitor, Don't Alert)

1. **Email delivery rate**: Target > 95%, but not critical
2. **Webhook retry rate**: Informational, expected to be low

---

## When to Upgrade

### Keep This Simple Architecture If:
- ✅ Webhook retries are rare (< 5%)
- ✅ Email service is reliable (> 95% uptime)
- ✅ Duplicate emails acceptable (low customer impact)
- ✅ Order volume < 10,000/day

### Consider Upgrade If:
- ⚠️ Email duplicates causing customer complaints
- ⚠️ Email service frequently down (< 90% uptime)
- ⚠️ Need strict exactly-once delivery guarantees
- ⚠️ Order volume > 100,000/day

### Upgrade Path (If Needed)

**Phase 1**: Add `EmailLog` table
```python
class EmailLog(Base):
    order_id = Column(Integer, ForeignKey('orders.id'))
    email_type = Column(String)  # 'customer' | 'admin'
    sent_at = Column(DateTime)
    status = Column(String)  # 'sent' | 'failed'
```

Check `EmailLog` before sending → idempotent without domain pollution.

**Phase 2**: Async queue (Celery/RQ)
```python
# Webhook handler
order = create_order(...)
send_customer_email.delay(order.id)  # Async, retryable
```

Queue handles retries, deduplication, rate limiting.

---

## Summary

### What This Architecture Achieves

✅ **Correctness**: Database guarantees money state  
✅ **Simplicity**: Clean domain model, obvious flow  
✅ **Maintainability**: Easy to understand and debug  
✅ **Production-ready**: Handles retries, races, failures  

### What It Intentionally Doesn't Solve

⚠️ **Perfect email deduplication**: Best-effort is sufficient  
⚠️ **Guaranteed side-effect delivery**: Acceptable trade-off  
⚠️ **Distributed transaction guarantees**: Not needed for MVP  

### Key Insight

> "A simple system that handles 99% of cases correctly is better than a complex system that handles 100% of cases theoretically."

This is **production-grade architecture** without over-engineering.

---

## References

- Stripe PaymentIntent API: Single source of truth, idempotent by key
- Martin Fowler on Event Sourcing: Use when you need full audit trail (we don't yet)
- Rich Hickey on Simplicity: "Simple Made Easy" - prefer simple over complex
