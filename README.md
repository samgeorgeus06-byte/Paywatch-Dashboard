# PayWatch

## Real-Time Fraud Detection for Merchant Payments

PayWatch is a merchant payment dashboard that processes live card transactions and flags suspicious activity as it happens. It ingests Stripe webhooks, records every transaction in DynamoDB, scores each one against five fraud rules, and sends alerts through AWS SNS when a transaction trips a rule. End-of-day activity summaries are generated through the Anthropic Claude API.

Deployed and running in production on AWS EC2.

## Features

### Payments

- Stripe Checkout Sessions for card capture (test mode)
- Signature-verified webhook endpoint consuming `checkout.session.completed`, `charge.refunded`, `charge.dispute.created`, and `payment_intent.payment_failed`
- Refunds and disputes update existing transaction records by payment intent ID

### Fraud Detection

Every transaction is evaluated against five rules on arrival:

| Rule | Trigger |
| :--- | :--- |
| Large amount | Single transaction over $500 |
| Velocity | 3+ transactions from the same email within 10 minutes |
| Repeated failures | 3+ failed payment attempts from the same email |
| Round amount | Exact round totals, a common card-testing signal |
| Odd hours | Transactions between 2:00 and 5:00 UTC |

Matches publish to an SNS topic, which delivers an email alert naming the transaction and the rules it triggered.

### Storage

- `merchant_transactions` — every transaction, keyed by transaction ID
- `failed_payment_attempts` — failed attempt counts, keyed by email, backing the repeated-failure rule

Both accessed through boto3 with IAM-scoped credentials.

### AI Summaries

Aggregated daily statistics and flagged-transaction detail are sent to the Anthropic Claude API (`claude-haiku-4-5`), which returns a plain-language summary of the day's payment activity for the dashboard.

### Dashboard

- Chart.js revenue visualization over a seven-day window
- Stat cards for revenue, transaction count, refunds, and disputes
- Recent transaction table with fraud flags surfaced inline

## Architecture

Single Flask application serving all routes, with three service modules isolating external systems. This is intentionally a monolith — appropriate at this scale. The natural first split would be moving webhook processing behind a queue.

```
app.py                          Flask routes + Stripe webhook handler
├── services/stripe_service.py  Stripe Checkout session creation
├── services/dynamo_service.py  DynamoDB reads and writes
├── services/fraud_detection.py Fraud rules + SNS alerting
└── services/ai_summary.py      Claude API daily summary
templates/                      dashboard, checkout, success, cancel
```

## API

| Route | Method | Returns |
| :--- | :--- | :--- |
| `/dashboard` | GET | Main dashboard page |
| `/checkout` | GET | Demo payment page |
| `/api/transactions` | GET | 50 most recent transactions |
| `/api/analytics` | GET | Seven-day revenue series |
| `/api/summary` | GET | Aggregate stat card totals |
| `/api/daily-summary` | GET | AI-generated daily summary |
| `/create-checkout-session` | POST | Creates a Stripe Checkout session |
| `/webhook` | POST | Receives Stripe events |

## Stack

Python 3 · Flask · Stripe API · AWS (EC2, DynamoDB, SNS, IAM) · Anthropic Claude API · Chart.js · gunicorn

## Running Locally

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
STRIPE_WEBHOOK_SECRET=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=
SNS_TOPIC_ARN=
APP_URL=http://localhost:5000
PORT=5000
```

Requires two DynamoDB tables (`merchant_transactions`, partition key `transaction_id`; `failed_payment_attempts`, partition key `email`) and an SNS topic with a confirmed email subscription.

```bash
python app.py
```

For local webhook delivery, forward events with the Stripe CLI:

```bash
stripe listen --forward-to localhost:5000/webhook
```

## Roadmap

- Move webhook ingestion onto SQS with a dedicated worker so event processing scales independently of web traffic
- nginx reverse proxy with TLS termination on a registered domain
- CloudWatch metrics and alarms on webhook failure rates
- Replace the static rule engine with a scored model trained on accumulated transaction history
