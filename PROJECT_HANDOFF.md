# PayWatch — Project Handoff / Context Restore

**Last updated:** August 8, 2026
**Purpose:** Full context snapshot so work can resume after a clean Windows reinstall.
Give this file to Claude at the start of a new session to restore context.

---

## 1. What This Project Is

**PayWatch** — a fintech merchant payment dashboard. Portfolio project built by Sam
(samgeorgeus06@gmail.com) to demonstrate full-stack + cloud + AI integration skills.

**Stack:** Python / Flask · Stripe API · AWS (EC2, DynamoDB, SNS, IAM) · Anthropic Claude API · Chart.js

**What it does:**
- Accepts card payments via Stripe Checkout (test mode)
- Receives Stripe webhooks for payments, refunds, disputes, failed payments
- Stores every transaction in DynamoDB
- Runs rule-based fraud detection on each transaction
- Emails fraud alerts via AWS SNS
- Generates an AI-written end-of-day summary using Claude (Haiku)
- Displays everything on a live dashboard with revenue charts

---

## 2. Current Status — DEPLOYED AND WORKING

Everything below is confirmed working in production as of Jul 29, 2026.

| Item | Status |
|---|---|
| Local development | Working |
| AI daily summary feature | Working |
| GitHub repo | Pushed (1 small uncommitted change — see §6) |
| EC2 deployment | Live |
| Stripe production webhook | Live |
| Elastic IP (permanent address) | Assigned |
| LinkedIn post | **NOT DONE** |
| Codebase teaching walkthrough | **NOT DONE** |

---

## 3. Live Infrastructure — Key Facts

| Thing | Value |
|---|---|
| **Elastic IP (permanent)** | `18.219.17.228` |
| Live dashboard | `http://18.219.17.228:5000/dashboard` |
| Live checkout | `http://18.219.17.228:5000/checkout` |
| Stripe webhook URL | `http://18.219.17.228:5000/webhook` |
| GitHub repo | https://github.com/samgeorgeus06-byte/Paywatch-Dashboard |
| AWS region | **us-east-2 (Ohio)** |
| AWS account ID | 263296415079 |
| EC2 instance name | `merchant-dashboard` (Ubuntu, t2.micro) |
| EC2 instance ID | i-049a7c7b60b1a4e82 |
| SSH key file | `merchant-key.pem` |
| DynamoDB tables | `merchant_transactions` (PK: transaction_id), `failed_payment_attempts` (PK: email) |
| SNS topic | `merchant-fraud-alerts` |
| SNS Topic ARN | `arn:aws:sns:us-east-2:263296415079:merchant-fraud-alerts` |
| Claude model used | `claude-haiku-4-5-20251001` |

### Server paths / commands

```bash
# Connect
ssh -i "merchant-key.pem" ubuntu@18.219.17.228

# Project location on server
cd ~/Paywatch-Dashboard
source venv/bin/activate       # MUST run this before python/pip commands

# Restart the app
pkill gunicorn
gunicorn app:app --bind 0.0.0.0:5000 --daemon --workers 1

# Check it's running
ps aux | grep gunicorn
```

Notes:
- Server has a 2GB swap file added (t2.micro only has ~1GB RAM).
- Runs 1 gunicorn worker deliberately (each worker loads Stripe + boto3 + Anthropic ≈ 140MB).
- Stripe CLI is only needed for LOCAL testing, not production.

---

## 4. Architecture — How It Fits Together

Single Flask monolith (`app.py`) serving all routes. Three service modules handle
external systems. Design note: this is intentionally a monolith — appropriate at this
scale. Natural first split, if scaled, would be moving webhook processing to its own
service or a queue.

```
app.py                          Flask routes + Stripe webhook handler
├── services/stripe_service.py  Creates Stripe Checkout sessions
├── services/dynamo_service.py  All DynamoDB reads/writes
├── services/fraud_detection.py Fraud rules + SNS alerting
└── services/ai_summary.py      Claude API call for daily summary
templates/                      dashboard.html, checkout.html, success.html, cancel.html
```

### Routes
| Route | Purpose |
|---|---|
| `/` | redirects to /dashboard |
| `/dashboard` | main dashboard page |
| `/checkout` | test payment page |
| `/success`, `/cancel` | post-payment pages |
| `/api/transactions` | JSON: 50 recent transactions |
| `/api/analytics` | JSON: 7-day revenue for chart |
| `/api/summary` | JSON: stat card totals |
| `/api/daily-summary` | JSON: AI-generated summary |
| `/create-checkout-session` | POST: creates Stripe session |
| `/webhook` | POST: receives Stripe events |

### Fraud rules (in `fraud_detection.py`)
1. **Large amount** — over $500
2. **Velocity** — 3+ transactions from same email in 10 min
3. **Repeated failures** — 3+ failed payment attempts from same email *(built by Sam)*
4. **Round amount** — exact round numbers (card-testing signal)
5. **Odd hours** — 2am–5am UTC

---

## 5. What Sam Personally Built and Debugged

Important for interview honesty. The initial scaffolding was AI-assisted; the following
was Sam's own work, hands-on:

- **Repeated-failures fraud rule, end to end** — `get_failed_attempt_count()` in
  dynamo_service.py, the rule logic in fraud_detection.py, and the alert-email description.
- **Debugged the `receipt_email` bug** — failed payments weren't being recorded because
  Stripe leaves `receipt_email` empty; the real email is nested at
  `last_payment_error.payment_method.billing_details.email`. Found by adding debug
  logging and reading actual webhook payloads.
- **Diagnosed duplicate webhook listener** — two `stripe.exe` processes were double-counting
  every event; found via Task Manager.
- **Found the malformed SNS ARN** — a subscription UUID had been appended to the topic ARN.
- **Correctly reasoned that the app wasn't crashing** — noted the SNS fraud email still
  arrived after checkout, proving the webhook chain completed. (This was right; the actual
  bug was `APP_URL` missing `:5000`, so Stripe's redirect hit port 80.)
- **All AWS infrastructure setup** — DynamoDB tables, SNS topic + subscription, IAM user
  and policies, EC2 instance, security groups, Elastic IP.
- **The full EC2 deployment**, including venv setup, swap file, gunicorn.

---

## 6. Immediate Next Steps (in order)

1. **Commit the one pending change** — `services/ai_summary.py` (prompt was rewritten to be
   factual/direct, no markdown, no reassurance language). Not yet pushed.
   ```
   git add .
   git commit -m "Refine AI summary prompt tone"
   git push
   ```
2. **Full codebase teaching walkthrough** — go through every file and function so Sam knows
   the system deeply, not just the parts he wrote. He explicitly asked for this and it matters:
   he wants to be able to defend this project in interviews.
3. **Write and publish the LinkedIn post.** Original deadline was Aug 1, 2026 — that has passed.
   Plan was: screenshots/short video + GitHub link (NOT the raw live IP, to avoid strangers
   burning Anthropic credits or spamming test payments).
4. **After AWS Cloud Practitioner exam** — build a structured plan to deepen Sam's actual
   Python skills so he can build independently.

---

## 7. Known Issues / Cleanup Items

- `fraud_detection.py` logs the repeated-failures rule as "Rule 2.5" — cosmetic mislabel.
- Rule numbering in comments is out of order (Repeated Failures inserted after Rule 2).
- Minor typos in some docstrings (`dymanmo_service`, `emaail`).
- **Security group has port 22 (SSH) open to `0.0.0.0/0`** — should be restricted to
  Sam's IP for anything long-lived.
- No HTTPS — plain HTTP on port 5000. Fine for a demo, would need a domain +
  reverse proxy (nginx) + certificate for anything real.
- Elastic IP costs money if left allocated while the instance is stopped/terminated.
  Release it if tearing the project down.

---

## 8. Working Style Notes (for Claude)

- Sam is a **beginner** — knows only basic Python. Explain concepts in plain English before
  showing code. Avoid unexplained jargon; he will say so if lost, and that's a signal to
  back up, not to push forward.
- He explicitly wants to **learn by doing** — he types the code, Claude reviews. Do not just
  write features for him unless he asks. He has said the whole point is to get his hands dirty.
- Environment/tooling problems (PATH issues, installs) have eaten far more time than the
  actual code. On Windows, `winget` installs often need a full terminal/VS Code restart, and
  sometimes a manual PATH entry.
- **Get logs before theorizing.** Two separate bugs in this project were misdiagnosed by
  guessing at causes instead of reading actual error output first.
