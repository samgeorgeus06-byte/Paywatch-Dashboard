# =============================================================================
# services/dynamo_service.py — DynamoDB database operations
# =============================================================================
# What is DynamoDB?
# ----------------
# DynamoDB is AWS's serverless NoSQL database. "NoSQL" means instead of
# rows and columns like Excel/SQL, we store items as JSON-like documents.
#
# Why DynamoDB for this project?
# - No server to manage (AWS handles everything)
# - Scales automatically
# - Free tier: 25 GB storage + 200 million requests/month (plenty for us)
# - Works great with Python via the boto3 library
#
# Our table: "merchant_transactions"
# Primary key: "transaction_id" (String) — uniquely identifies each payment
# =============================================================================

import os
import boto3
from datetime import datetime, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv

load_dotenv()

# How many days of data to consider "recent" for analytics
ANALYTICS_WINDOW_DAYS = 7


class DynamoService:
    """
    Handles all reads and writes to our DynamoDB table.
    We use a class so we only connect to AWS once (in __init__)
    and reuse that connection for every operation.
    """

    def __init__(self):
        # boto3 is the AWS SDK for Python — it lets Python talk to any AWS service.
        # It reads credentials from environment variables automatically:
        #   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
        self.dynamodb = boto3.resource(
            "dynamodb",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )

        # Reference to our table — doesn't actually query anything yet
        self.table = self.dynamodb.Table("merchant_transactions")

        # A separate table to track failed payment attempts per email (for fraud)
        self.failed_attempts_table = self.dynamodb.Table("failed_payment_attempts")

    # -------------------------------------------------------------------------
    # WRITE OPERATIONS
    # -------------------------------------------------------------------------

    def save_transaction(self, transaction: dict):
        """
        Saves a new transaction to DynamoDB.

        DynamoDB doesn't accept Python floats (floating point precision issues
        with money), so we convert dollar amounts to Decimal before saving.

        Args:
            transaction: A dict with transaction_id, amount, currency, etc.
        """
        # Convert any float values to Decimal (DynamoDB requirement for numbers)
        item = self._convert_floats(transaction)
        self.table.put_item(Item=item)
        print(f"[DYNAMO] Saved transaction: {transaction.get('transaction_id')}")

    def update_transaction_status(self, payment_intent_id: str, new_status: str):
        """
        Updates the status of a transaction when a refund or dispute comes in.
        We look up by payment_intent_id since that's what Stripe sends us.

        Args:
            payment_intent_id: The Stripe payment intent ID (starts with pi_)
            new_status: "refunded" or "disputed"
        """
        # Scan for the transaction with this payment_intent_id
        # (In production you'd use a Global Secondary Index for efficiency)
        response = self.table.scan(
            FilterExpression=Attr("payment_intent_id").eq(payment_intent_id)
        )
        items = response.get("Items", [])

        for item in items:
            self.table.update_item(
                Key={"transaction_id": item["transaction_id"]},
                UpdateExpression="SET #s = :status, updated_at = :updated",
                ExpressionAttributeNames={"#s": "status"},  # 'status' is a reserved word
                ExpressionAttributeValues={
                    ":status": new_status,
                    ":updated": datetime.utcnow().isoformat(),
                },
            )
            print(f"[DYNAMO] Updated transaction {item['transaction_id']} → {new_status}")

    def update_fraud_flags(self, transaction_id: str, flags: list):
        """
        Adds fraud flag reasons to a transaction record.

        Args:
            transaction_id: The transaction to flag
            flags: List of reason strings, e.g. ["large_amount", "velocity_exceeded"]
        """
        self.table.update_item(
            Key={"transaction_id": transaction_id},
            UpdateExpression="SET fraud_flags = :flags, is_flagged = :flagged",
            ExpressionAttributeValues={
                ":flags": flags,
                ":flagged": True,
            },
        )

    def record_failed_attempt(self, email: str):
        """
        Increments the failed payment attempt counter for an email address.
        Used by fraud detection to catch repeated card failures.

        Args:
            email: The customer's email address
        """
        try:
            self.failed_attempts_table.update_item(
                Key={"email": email},
                UpdateExpression="ADD attempt_count :one SET last_attempt = :now",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":now": datetime.utcnow().isoformat(),
                },
            )
        except Exception as e:
            print(f"[DYNAMO] Could not record failed attempt: {e}")
    def get_failed_attempt_count(self, email: str)-> int:
        """
        Looks up how many times this emaail has had a failed attempt.
        Return 0 if the email has never failed a payment
        """
        response =  self.failed_attempts_table.get_item(Key={"email": email})
        return response.get("Item", {}).get("attempt_count", 0)
    # -------------------------------------------------------------------------
    # READ OPERATIONS
    # -------------------------------------------------------------------------

    def get_recent_transactions(self, limit: int = 50) -> list:
        """
        Returns the most recent transactions, sorted newest first.
        DynamoDB doesn't natively sort by a non-key attribute, so we
        scan, sort in Python, then return the top N results.

        Args:
            limit: Max number of transactions to return

        Returns:
            List of transaction dicts
        """
        response = self.table.scan(Limit=200)  # Pull up to 200, then sort
        items = response.get("Items", [])

        # Sort by created_at (newest first)
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Convert Decimal back to float for JSON serialization
        return [self._convert_decimals(item) for item in items[:limit]]

    def get_revenue_analytics(self) -> dict:
        """
        Calculates daily revenue totals for the past 7 days.
        Returns data in the format Chart.js expects: labels + data arrays.

        Returns:
            {
                "labels": ["2026-05-09", "2026-05-10", ...],
                "revenue": [1500, 3200, ...],        # In cents
                "transaction_counts": [3, 7, ...]
            }
        """
        # Build list of the last 7 day strings
        today = datetime.utcnow().date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

        # Fetch transactions from the last 7 days
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        response = self.table.scan(
            FilterExpression=Attr("created_at").gte(cutoff)
            & Attr("status").eq("succeeded")
        )
        items = response.get("Items", [])

        # Group by day
        daily = {day: {"revenue": 0, "count": 0} for day in days}
        for item in items:
            day = item.get("created_at", "")[:10]  # "2026-05-15T..." → "2026-05-15"
            if day in daily:
                daily[day]["revenue"] += int(item.get("amount", 0))
                daily[day]["count"] += 1

        return {
            "labels": days,
            "revenue": [daily[d]["revenue"] for d in days],       # Cents
            "transaction_counts": [daily[d]["count"] for d in days],
        }

    def get_summary(self) -> dict:
        """
        Returns high-level stats shown in the dashboard summary cards.

        Returns:
            {
                "total_revenue_cents": 125000,
                "transaction_count": 42,
                "refund_count": 3,
                "dispute_count": 1,
                "flagged_count": 2
            }
        """
        response = self.table.scan()
        items = response.get("Items", [])

        total_revenue = sum(
            int(item.get("amount", 0))
            for item in items
            if item.get("status") == "succeeded"
        )
        refund_count = sum(1 for item in items if item.get("status") == "refunded")
        dispute_count = sum(1 for item in items if item.get("status") == "disputed")
        flagged_count = sum(1 for item in items if item.get("is_flagged", False))

        return {
            "total_revenue_cents": total_revenue,
            "transaction_count": len([i for i in items if i.get("status") == "succeeded"]),
            "refund_count": refund_count,
            "dispute_count": dispute_count,
            "flagged_count": flagged_count,
        }

    def get_recent_transactions_for_email(self, email: str, minutes: int = 10) -> list:
        """
        Returns transactions for a specific email in the last N minutes.
        Used by fraud detection to check for velocity (too many transactions too fast).

        Args:
            email: Customer email to look up
            minutes: Time window to check

        Returns:
            List of matching transactions
        """
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        response = self.table.scan(
            FilterExpression=Attr("customer_email").eq(email)
            & Attr("created_at").gte(cutoff)
        )
        return response.get("Items", [])

    def get_todays_transactions(self) -> list:
        """
        Returns all transactions created today (UTC).
        Used to build the data the AI summary is generated from.
        """
        today_str = datetime.utcnow().date().isoformat()  # e.g. "2026-07-22"
        response = self.table.scan(
            FilterExpression=Attr("created_at").begins_with(today_str)
        )
        items = response.get("Items", [])
        return [self._convert_decimals(item) for item in items]
        
    # -------------------------------------------------------------------------
    # HELPER METHODS — DynamoDB ↔ Python type conversion
    # -------------------------------------------------------------------------

    def _convert_floats(self, obj):
        """
        Recursively converts float values to Decimal.
        DynamoDB requires Decimal for all numeric types (not float).
        """
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats(i) for i in obj]
        return obj

    def _convert_decimals(self, obj):
        """
        Recursively converts Decimal back to float/int when reading from DynamoDB.
        We need this because JSON doesn't know about Decimal — only float/int.
        """
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        elif isinstance(obj, dict):
            return {k: self._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_decimals(i) for i in obj]
        return obj
