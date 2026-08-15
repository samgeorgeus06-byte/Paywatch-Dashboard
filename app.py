
import os
import json
from datetime import datetime

import stripe
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv

from services.stripe_service import create_checkout_session
from services.dynamo_service import DynamoService
from services.fraud_detection import FraudDetector
from services.ai_summary import generate_daily_summary

load_dotenv()
app = Flask(__name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
dynamo = DynamoService()        
fraud_detector = FraudDetector() 


@app.route("/")
def index():
    """Redirect the root URL to the dashboard."""
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    """Render the main merchant dashboard HTML page."""
    return render_template("dashboard.html")


@app.route("/checkout")
def checkout():
    """Render the demo customer checkout page."""
    return render_template("checkout.html")


@app.route("/success")
def success():
    """Page shown after a successful payment."""
    return render_template("success.html")


@app.route("/cancel")
def cancel():
    """Page shown when a customer cancels checkout."""
    return render_template("cancel.html")


@app.route("/api/transactions")
def api_transactions():
    """
    Returns the 50 most recent transactions stored in DynamoDB.
    The dashboard's JS calls this every 30 seconds to stay up to date.
    """
    try:
        transactions = dynamo.get_recent_transactions(limit=50)
        return jsonify({"status": "ok", "data": transactions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/analytics")
def api_analytics():
    """
    Returns revenue data broken down by day for the last 7 days.
    Used to draw the revenue trend chart on the dashboard.
    """
    try:
        analytics = dynamo.get_revenue_analytics()
        return jsonify({"status": "ok", "data": analytics})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/summary")
def api_summary():
    """
    Returns high-level stats: total revenue, transaction count,
    refund count, and dispute count. Shown in the stat cards at the top.
    """
    try:
        summary = dynamo.get_summary()
        return jsonify({"status": "ok", "data": summary})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/daily-summary")
def api_daily_summary():
    """
    Generates and returns an AI-written summary of today's payment activity.
    Calls Claude via services/ai_summary.py.
    """
    try:
        summary = generate_daily_summary(dynamo)
        return jsonify({"status": "ok", "summary": summary})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout():
    """
    Receives a request from the checkout page with an amount,
    creates a Stripe Checkout Session, and returns the URL.
    The frontend then redirects the customer to that Stripe-hosted URL.
    """
    try:
        data = request.get_json()
        amount = int(data.get("amount", 2000))  # Amount in cents (2000 = $20.00)
        description = data.get("description", "Merchant Dashboard Demo Purchase")

        # Create the Stripe Checkout Session (see stripe_service.py)
        session = create_checkout_session(amount, description)

        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receives real-time payment events from Stripe.
    This is how we know a payment went through — Stripe tells us.
    """
    payload = request.data  # Raw bytes of the request body
    sig_header = request.headers.get("Stripe-Signature")

    # Step 1: Verify the webhook really came from Stripe
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Payload was malformed
        print("[WEBHOOK] Invalid payload received")
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        # Signature didn't match — possible spoofing attempt
        print("[WEBHOOK] Invalid signature — possible spoofing attempt!")
        return "Invalid signature", 400

    event_type = event["type"]
    print(f"[WEBHOOK] Received event: {event_type}")

    # Step 2: Handle each event type we care about
    if event_type == "checkout.session.completed":
        # A customer successfully paid!
        session_obj = event["data"]["object"]

        transaction = {
            "transaction_id": session_obj["id"],
            "payment_intent_id": session_obj.get("payment_intent", ""),
            "amount": session_obj["amount_total"],       # In cents
            "currency": session_obj["currency"].upper(),
            "status": "succeeded",
            "customer_email": (session_obj.get("customer_details") or {}).get("email", "unknown"),
            "created_at": datetime.utcnow().isoformat(),
            "fraud_flags": [],
        }

        # Save to DynamoDB
        dynamo.save_transaction(transaction)

        # Run fraud detection
        fraud_result = fraud_detector.analyze(transaction, dynamo)
        if fraud_result["is_suspicious"]:
            transaction["fraud_flags"] = fraud_result["reasons"]
            dynamo.update_fraud_flags(transaction["transaction_id"], fraud_result["reasons"])
            fraud_detector.send_alert(transaction, fraud_result["reasons"])
            print(f"[FRAUD ALERT] Transaction {transaction['transaction_id']} flagged: {fraud_result['reasons']}")

    elif event_type == "charge.refunded":
        # A refund was issued
        charge = event["data"]["object"]
        payment_intent_id = charge.get("payment_intent", "")
        dynamo.update_transaction_status(payment_intent_id, "refunded")
        print(f"[WEBHOOK] Refund processed for payment_intent: {payment_intent_id}")

    elif event_type == "charge.dispute.created":
        # A customer disputed a charge (chargeback)
        dispute = event["data"]["object"]
        payment_intent_id = dispute.get("payment_intent", "")
        dynamo.update_transaction_status(payment_intent_id, "disputed")
        print(f"[WEBHOOK] Dispute opened for payment_intent: {payment_intent_id}")

    elif event_type == "payment_intent.payment_failed":
        # A payment attempt failed (wrong card number, insufficient funds, etc.)
        payment_intent = event["data"]["object"]
        # Track failed attempts for fraud detection (repeated failures = suspicious)
        last_error = payment_intent.get("last_payment_error") or {}
        payment_method = last_error.get("payment_method") or {}
        billing_details = payment_method.get("billing_details") or {}
        email = billing_details.get("email") or payment_intent.get("receipt_email") or "unknown"

        dynamo.record_failed_attempt(email)
        print(f"[WEBHOOK] Payment Failed: {payment_intent['id']} (email: {email})")

    return jsonify({"status": "received"})

# Run the app
# debug=True means Flask will reload automatically when you edit code.
# In production on AWS, we won't use debug mode.


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
