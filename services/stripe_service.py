# =============================================================================
# services/stripe_service.py — All Stripe API calls live here
# =============================================================================
# Why a separate file? Separation of concerns — app.py handles routing,
# this file handles Stripe. If Stripe changes their API, we only edit
# this one file instead of hunting through app.py.
# =============================================================================

import os
import stripe
from dotenv import load_dotenv

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# The URL of our app — Stripe redirects customers back here after payment
APP_URL = os.getenv("APP_URL", "http://localhost:5000")


def create_checkout_session(amount_cents: int, description: str = "Demo Purchase"):
    """
    Creates a Stripe Checkout Session.

    What is a Checkout Session?
    ---------------------------
    When a customer is ready to pay, we create a "session" on Stripe's servers.
    Stripe gives us back a URL. We send the customer to that URL.
    The customer enters their card on Stripe's secure page (not ours!).
    Stripe processes the payment, then redirects them back to our /success page.

    Args:
        amount_cents: The price in cents. $10.00 = 1000 cents.
        description:  What the customer is buying (shows on their receipt).

    Returns:
        A Stripe Session object. We use session.url to redirect the customer.
    """
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],  # Accept credit/debit cards
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,   # In cents
                    "product_data": {
                        "name": description,
                        "description": "Processed via Merchant Dashboard",
                    },
                },
                "quantity": 1,
            }
        ],
        mode="payment",                                    # One-time payment (not subscription)
        success_url=f"{APP_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_URL}/cancel",
        billing_address_collection="auto",                 # Collect billing address
        customer_creation="always",                        # Always create a Stripe customer record
    )
    return session


def get_stripe_transactions(limit: int = 50):
    """
    Fetches recent payment intents directly from Stripe's API.
    Useful as a fallback if DynamoDB data is missing or to cross-check.

    Args:
        limit: How many records to fetch (max 100 per Stripe API call).

    Returns:
        A list of payment intent objects.
    """
    payment_intents = stripe.PaymentIntent.list(limit=limit)
    results = []

    for pi in payment_intents.auto_paging_iter():
        results.append({
            "id": pi["id"],
            "amount": pi["amount"],
            "currency": pi["currency"].upper(),
            "status": pi["status"],
            "created": pi["created"],   # Unix timestamp
        })
        if len(results) >= limit:
            break

    return results


def get_stripe_refunds(limit: int = 20):
    """
    Fetches recent refunds from Stripe.

    Returns:
        A list of refund objects with amount, reason, and status.
    """
    refunds = stripe.Refund.list(limit=limit)
    return [
        {
            "id": r["id"],
            "amount": r["amount"],
            "currency": r["currency"].upper(),
            "status": r["status"],
            "reason": r.get("reason", "not_specified"),
            "created": r["created"],
        }
        for r in refunds.auto_paging_iter()
    ]


def get_stripe_disputes(limit: int = 20):
    """
    Fetches recent disputes (chargebacks) from Stripe.
    A dispute means a customer told their bank they didn't authorize a charge.

    Returns:
        A list of dispute objects.
    """
    disputes = stripe.Dispute.list(limit=limit)
    return [
        {
            "id": d["id"],
            "amount": d["amount"],
            "currency": d["currency"].upper(),
            "status": d["status"],
            "reason": d["reason"],
            "created": d["created"],
        }
        for d in disputes.auto_paging_iter()
    ]
