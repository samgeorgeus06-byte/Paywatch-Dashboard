# =============================================================================
# services/fraud_detection.py — Basic fraud detection rules engine
# =============================================================================
# Real fintech companies use ML models for fraud detection, but even
# simple rule-based systems catch a lot of fraud. Here we implement
# 4 straightforward rules:
#
#   Rule 1 — Large Amount:       Single transaction > $500
#   Rule 2 — Velocity Check:     Same customer, 3+ transactions in 10 minutes
#   Rule 3 — Repeated Failures:  Same email fails payment 3+ times
#   Rule 4 — Round Number:       Exact round amounts ($100, $200) are
#                                 sometimes used in card testing attacks
#
# When a transaction triggers a rule, we:
#   1. Record the flags on the transaction in DynamoDB
#   2. Send an alert email via AWS SNS
# =============================================================================

import os
import boto3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Thresholds — tweak these based on your business's typical transaction sizes
LARGE_AMOUNT_THRESHOLD_CENTS = 50_000   # $500.00
VELOCITY_WINDOW_MINUTES = 10            # Time window for velocity check
VELOCITY_MAX_TRANSACTIONS = 3           # Max allowed transactions in window
FAILED_ATTEMPTS_THRESHOLD = 3          # Failed payments before flagging


class FraudDetector:
    """
    Analyzes transactions against rule-based fraud detection criteria.
    Sends alerts via AWS SNS (Simple Notification Service) when fraud is detected.
    """

    def __init__(self):
        # AWS SNS client — used to send alert emails to the merchant
        self.sns = boto3.client(
            "sns",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        # The ARN (Amazon Resource Name) of our SNS topic.
        # You'll create this topic in AWS and paste its ARN here.
        self.sns_topic_arn = os.getenv("SNS_TOPIC_ARN", "")

    def analyze(self, transaction: dict, dynamo_service=None) -> dict:
        """
        Runs all fraud rules against a transaction.

        Args:
            transaction:    The transaction dict (from our webhook handler)
            dynamo_service: The DynamoDB service instance (for historical lookups)

        Returns:
            {
                "is_suspicious": True/False,
                "reasons": ["large_amount", "velocity_exceeded"]   # List of triggered rules
            }
        """
        reasons = []
        amount = transaction.get("amount", 0)  # In cents
        email = transaction.get("customer_email", "unknown")

        # ------------------------------------------------------------------
        # Rule 1: Large Amount
        # Transactions over $500 are flagged for manual review.
        # The threshold should match what's "normal" for your business.
        # ------------------------------------------------------------------
        if amount > LARGE_AMOUNT_THRESHOLD_CENTS:
            reasons.append("large_amount")
            print(f"[FRAUD] Rule 1 triggered: amount ${amount/100:.2f} exceeds threshold")

        # ------------------------------------------------------------------
        # Rule 2: Velocity Check
        # If the same customer makes 3+ transactions in 10 minutes,
        # that's unusual — could be a stolen card being tested.
        # ------------------------------------------------------------------
        if dynamo_service and email != "unknown":
            recent = dynamo_service.get_recent_transactions_for_email(
                email, minutes=VELOCITY_WINDOW_MINUTES
            )
            if len(recent) >= VELOCITY_MAX_TRANSACTIONS:
                reasons.append("velocity_exceeded")
                print(f"[FRAUD] Rule 2 triggered: {len(recent)} transactions from {email} in {VELOCITY_WINDOW_MINUTES}min")
        if dynamo_service and email != "unknown":
            failed_count = dynamo_service.get_failed_attempt_count(email)
            if failed_count >= FAILED_ATTEMPTS_THRESHOLD:
                reasons.append("repeated_failures")
                print(f"[FRAUD] Rule 2.5 triggered: {email} has {failed_count} failed attempts")
        # ------------------------------------------------------------------
        # Rule 3: Round Number Detection
        # Card-testing fraud often uses exact round amounts.
        # $100.00, $200.00, $500.00 etc. — amount in cents divisible by 10000
        # ------------------------------------------------------------------
        if amount > 0 and amount % 10_000 == 0:
            reasons.append("suspicious_round_amount")
            print(f"[FRAUD] Rule 3 triggered: suspiciously round amount ${amount/100:.2f}")

        # ------------------------------------------------------------------
        # Rule 4: Odd Hours
        # Transactions between 2am–5am UTC are statistically more
        # likely to be fraudulent (most legitimate customers are asleep).
        # ------------------------------------------------------------------
        hour = datetime.utcnow().hour
        if 2 <= hour <= 5:
            reasons.append("odd_hours")
            print(f"[FRAUD] Rule 4 triggered: transaction at {hour:02d}:00 UTC (odd hours)")

        return {
            "is_suspicious": len(reasons) > 0,
            "reasons": reasons,
        }

    def send_alert(self, transaction: dict, reasons: list):
        """
        Sends an email alert to the merchant via AWS SNS.

        What is SNS?
        -----------
        SNS (Simple Notification Service) is AWS's pub/sub messaging system.
        We create a "topic," subscribe our email to it, and then
        whenever we "publish" a message to the topic, AWS emails us.
        It's like a notification bell — ring it and all subscribers hear it.

        Args:
            transaction: The suspicious transaction dict
            reasons:     List of fraud rule names that were triggered
        """
        if not self.sns_topic_arn:
            print("[FRAUD ALERT] SNS topic ARN not configured. Set SNS_TOPIC_ARN in .env")
            return

        amount_dollars = transaction.get("amount", 0) / 100
        transaction_id = transaction.get("transaction_id", "unknown")
        email = transaction.get("customer_email", "unknown")
        created_at = transaction.get("created_at", "unknown")

        # Format the reasons into readable descriptions
        reason_descriptions = {
            "large_amount": f"  • Transaction amount (${amount_dollars:.2f}) exceeds $500 threshold",
            "velocity_exceeded": f"  • Customer email ({email}) made {VELOCITY_MAX_TRANSACTIONS}+ transactions in {VELOCITY_WINDOW_MINUTES} minutes",
            "suspicious_round_amount": f"  • Suspiciously round transaction amount (${amount_dollars:.2f})",
            "odd_hours": f"  • Transaction occurred at an unusual hour (2am–5am UTC)",
            "repeated_failures": f"  • Customer email ({email}) has {FAILED_ATTEMPTS_THRESHOLD}+ failed payment attempts",
        }

        reason_text = "\n".join(
            reason_descriptions.get(r, f"  • {r}") for r in reasons
        )

        subject = f"🚨 Fraud Alert — Transaction {transaction_id[:20]}..."

        message = f"""
FRAUD ALERT — Merchant Dashboard
==================================

A transaction has been flagged for suspicious activity.

Transaction Details:
  ID:       {transaction_id}
  Amount:   ${amount_dollars:.2f} USD
  Customer: {email}
  Time:     {created_at} UTC

Triggered Rules:
{reason_text}

---
Please review this transaction in your Merchant Dashboard.
If this is legitimate, you can dismiss the flag.
If this is fraud, consider issuing a refund and blocking the customer.

This alert was sent automatically by your fraud detection system.
        """.strip()

        try:
            response = self.sns.publish(
                TopicArn=self.sns_topic_arn,
                Subject=subject,
                Message=message,
            )
            print(f"[SNS] Alert sent. MessageId: {response['MessageId']}")
        except Exception as e:
            # Don't crash the whole app if SNS fails — just log it
            print(f"[SNS] Failed to send alert: {e}")
