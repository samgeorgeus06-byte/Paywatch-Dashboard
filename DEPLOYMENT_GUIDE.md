# PayWatch — Merchant Dashboard
## Full Deployment Guide (Beginner Friendly)

> **What we built:** A fintech merchant dashboard that accepts payments via Stripe Checkout, stores transaction data in AWS DynamoDB, detects fraud using rule-based logic, and sends alerts via AWS SNS (email).

---

## What Each Piece Does (Plain English)

| Component | What it is | What it does in our app |
|---|---|---|
| **Flask** | Python web framework | Serves pages, handles API calls |
| **Stripe** | Payment processor | Handles actual card payments securely |
| **DynamoDB** | AWS NoSQL database | Stores every transaction as a JSON record |
| **SNS** | AWS notification service | Sends you email alerts when fraud is detected |
| **EC2** | AWS virtual server | Runs our Flask app in the cloud |

---

## Part 1 — Set Up Stripe (5 minutes)

### 1.1 Create your free Stripe account

1. Go to **[stripe.com](https://stripe.com)** → click **Start now**
2. Enter your email, name, country, create a password
3. Verify your email
4. You are now in Stripe's **Dashboard**

> **Important:** You do NOT need to enter banking info for test mode. Test mode is free and lets you process fake payments.

### 1.2 Get your API Keys

1. In the Stripe Dashboard sidebar, click **Developers**
2. Click **API keys**
3. You'll see two keys:
   - **Publishable key** — starts with `pk_test_...` (safe to share publicly)
   - **Secret key** — starts with `sk_test_...` (**never share this — treat it like a password**)
4. Copy both keys and paste them into your `.env` file

```
STRIPE_SECRET_KEY=sk_test_51...
STRIPE_PUBLISHABLE_KEY=pk_test_51...
```

### 1.3 Install the Stripe CLI (for webhooks during local development)

The Stripe CLI lets Stripe send webhook events to your local machine.

**Mac:**
```bash
brew install stripe/stripe-cli/stripe
```

**Windows** — Download the installer from:
https://github.com/stripe/stripe-cli/releases/latest

Then log in:
```bash
stripe login
```

This opens a browser window — click **Allow access**.

---

## Part 2 — Set Up AWS (15 minutes)

You already have an AWS account. We need to:
1. Create a DynamoDB table
2. Create an SNS topic for fraud alert emails
3. Create an IAM user with the right permissions

### 2.1 Create the DynamoDB Table

> DynamoDB is like a giant JSON filing cabinet. Each "table" holds a collection of items (our transactions).

1. Go to **[AWS Console](https://console.aws.amazon.com)** → search for **DynamoDB** in the top search bar
2. Click **Create table**
3. Fill in:
   - **Table name:** `merchant_transactions`
   - **Partition key:** `transaction_id` (String)
   - Leave everything else as default
4. Click **Create table** → wait ~30 seconds

5. Repeat to create a second table:
   - **Table name:** `failed_payment_attempts`
   - **Partition key:** `email` (String)

### 2.2 Create an SNS Topic (for fraud alerts)

> SNS is like a group email list. We create a "topic," subscribe your email to it, and then whenever we "publish" a message, everyone subscribed gets an email.

1. In AWS Console, search for **SNS** → click **Simple Notification Service**
2. Click **Topics** in the left sidebar
3. Click **Create topic**
4. Choose **Standard** type
5. Name: `merchant-fraud-alerts`
6. Click **Create topic**

7. On the next page, click **Create subscription**
8. Protocol: **Email**
9. Endpoint: `samgeorgeus06@gmail.com`
10. Click **Create subscription**

11. **Check your email** — AWS sends a confirmation email. Click **Confirm subscription**.

12. Copy the **Topic ARN** (looks like `arn:aws:sns:us-east-1:123456789:merchant-fraud-alerts`)
13. Paste it into your `.env` file as `SNS_TOPIC_ARN=...`

### 2.3 Create an IAM User with Permissions

> IAM (Identity and Access Management) lets you create "sub-accounts" with specific permissions. We create one for our app so it can talk to DynamoDB and SNS.

1. In AWS Console, search for **IAM** → click it
2. Click **Users** in the left sidebar → **Create user**
3. Username: `merchant-dashboard-app`
4. Click **Next**
5. Select **Attach policies directly**
6. Search for and check these two policies:
   - `AmazonDynamoDBFullAccess`
   - `AmazonSNSFullAccess`
7. Click **Next** → **Create user**

8. Click on the newly created user → **Security credentials** tab
9. Click **Create access key** → choose **Application running outside AWS** → **Next**
10. Copy the **Access key ID** and **Secret access key**
11. Paste into your `.env`:
```
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1
```

> **Security note:** For a real production app, you'd use IAM Roles instead of access keys. For a portfolio/learning project, this approach is fine.

---

## Part 3 — Run Locally (5 minutes)

### 3.1 Install Python dependencies

Open a terminal in the project folder and run:

```bash
pip install -r requirements.txt
```

### 3.2 Set up your environment file

```bash
# Copy the template
cp .env.example .env

# Open .env in any text editor and fill in your actual keys
```

### 3.3 Start the Flask server

```bash
python app.py
```

You should see:
```
* Running on http://0.0.0.0:5000
* Debug mode: on
```

Open your browser and go to **http://localhost:5000** — you should see the dashboard!

### 3.4 Start the Stripe webhook listener (in a second terminal)

```bash
stripe listen --forward-to localhost:5000/webhook
```

You'll see something like:
```
> Ready! Your webhook signing secret is whsec_abc123...
```

Copy that `whsec_...` value and paste it into your `.env` as `STRIPE_WEBHOOK_SECRET`.

### 3.5 Make a test payment

1. Go to **http://localhost:5000/checkout**
2. Select a product amount
3. Click **Pay with Stripe →**
4. On Stripe's checkout page, enter the test card:
   - Card number: `4242 4242 4242 4242`
   - Expiry: `12/28`
   - CVC: `123`
   - ZIP: `10001`
5. Click **Pay**

You should be redirected to the success page.

**Check your dashboard** at http://localhost:5000/dashboard — the transaction should appear!

**Check your terminal** — you should see `[WEBHOOK]` log messages.

---

## Part 4 — Deploy to AWS EC2 (30 minutes)

> EC2 (Elastic Compute Cloud) is basically a computer in Amazon's data center that runs 24/7. We'll install our app on it so it's accessible from the internet.

### 4.1 Launch an EC2 Instance

1. In AWS Console → search **EC2** → **Launch instance**
2. Settings:
   - **Name:** `merchant-dashboard`
   - **AMI:** Ubuntu Server 22.04 LTS (free tier eligible)
   - **Instance type:** `t2.micro` (free tier — 1 CPU, 1GB RAM)
   - **Key pair:** Click **Create new key pair** → name it `merchant-key` → **RSA** → **.pem** → Download it
   - **Security group:** Click **Edit** and add these inbound rules:
     - SSH: Port 22, Source: My IP
     - HTTP: Port 80, Source: Anywhere (0.0.0.0/0)
     - Custom TCP: Port 5000, Source: Anywhere (for testing)
3. Click **Launch instance**

### 4.2 Connect to your EC2 instance

Find your instance's **Public IPv4 address** in the EC2 console (e.g., `54.123.45.67`).

**Mac/Linux:**
```bash
chmod 400 merchant-key.pem
ssh -i merchant-key.pem ubuntu@YOUR_EC2_IP
```

**Windows** — Use PuTTY or Windows Terminal with the .pem file.

### 4.3 Install Python and dependencies on EC2

Once connected via SSH (you're now typing inside the AWS server):

```bash
# Update Ubuntu's package list
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install python3 python3-pip -y

# Install git so we can download our code
sudo apt install git -y

# Clone your project (push it to GitHub first, or use scp to copy files)
git clone https://github.com/YOUR_USERNAME/merchant-dashboard.git
cd merchant-dashboard

# Install Python dependencies
pip3 install -r requirements.txt
```

### 4.4 Set up environment variables on EC2

```bash
# Create the .env file on the server
nano .env
```

Paste all your environment variables (same as local .env but update `APP_URL`):
```
APP_URL=http://YOUR_EC2_PUBLIC_IP
```

Press `Ctrl+X`, then `Y`, then `Enter` to save.

### 4.5 Run the app with Gunicorn

> `gunicorn` is a production-grade web server. Flask's built-in server is only for development.

```bash
# Run in background so it keeps running after you disconnect
gunicorn --bind 0.0.0.0:5000 app:app --daemon --workers 2

# Check it's running
ps aux | grep gunicorn
```

Now open your browser and go to **http://YOUR_EC2_IP:5000** — your dashboard is live on the internet!

### 4.6 Update Stripe Webhook URL

Since the app is now on EC2, tell Stripe where to send webhooks:

1. In Stripe Dashboard → **Developers** → **Webhooks**
2. Click **Add endpoint**
3. Endpoint URL: `http://YOUR_EC2_IP:5000/webhook`
4. Events to listen for: Select **checkout.session.completed**, **charge.refunded**, **charge.dispute.created**, **payment_intent.payment_failed**
5. Click **Add endpoint**
6. Click **Reveal signing secret** → copy the `whsec_...` value
7. Update `STRIPE_WEBHOOK_SECRET` in your `.env` on EC2, then restart gunicorn

---

## Part 5 — What to Say on LinkedIn

Here's how to describe this project in your LinkedIn profile / cover letters:

> **Merchant Payment Dashboard** | Python, Flask, Stripe API, AWS (EC2, DynamoDB, SNS)
>
> Built a full-stack fintech application featuring Stripe Checkout integration for secure card payments, real-time transaction monitoring with a Chart.js analytics dashboard, rule-based fraud detection (velocity checks, threshold alerts, card-testing detection), and automated email alerting via AWS SNS. Deployed on AWS EC2 with DynamoDB as the NoSQL transaction store.

**AWS services you can name:** EC2, DynamoDB, SNS, IAM
**Skills demonstrated:** REST API integration, webhook handling, event-driven architecture, cloud deployment, NoSQL databases, payment security (PCI compliance awareness)

---

## Troubleshooting Common Issues

**"ModuleNotFoundError: No module named 'flask'"**
→ Run `pip install -r requirements.txt` again

**Webhook events not showing up**
→ Make sure `stripe listen --forward-to localhost:5000/webhook` is running in a separate terminal

**DynamoDB permission error**
→ Double check your IAM user has `AmazonDynamoDBFullAccess` attached and your `.env` AWS keys are correct

**EC2 connection refused**
→ Check your Security Group has port 5000 open for inbound traffic

---

*Built with Flask + Stripe + AWS | Portfolio project by Sam*
