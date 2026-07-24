# =============================================================================
# services/ai_summary.py — AI-powered end-of-day summary
# =============================================================================
# This service asks Claude (Anthropic's AI) to read today's transaction data
# and write a short, human-readable summary — like a smart assistant giving
# you the highlights instead of you reading raw numbers yourself.
#
# How it works, in 3 steps:
#   1. Pull today's transactions from DynamoDB
#   2. Turn that data into a text description (a "prompt")
#   3. Send the prompt to Claude's API and get back written text
# =============================================================================
import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

#The ai client - like the stripe or boto 3 client in the other service
# files, this object is what we use to actually talk to claude's api 
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

## using haiku claudes cheapest fast model
## summarizing short list of numbers and keeps costs near-zero for this
MODEL_NAME = "claude-haiku-4-5-20251001"

def generate_daily_summary(dynamo_service) -> str:
    """
    Builds today transaction data, sends it to Claude and returns a short
    written summary of the day's payment activity.

    Args:
        dymanmo_service: the DynamoService instance (so we can read today's data)

    Returns:
        A string containing the AI-written summary.
    """
    transactions = dynamo_service.get_todays_transactions()
    
    #step 1: turn raw transaction into simple stats
    succeeded = [t for t in transactions if t.get("status") == "succeeded"]
    refunded = [t for t in transactions if t.get("status") == "refunded"]
    disputed = [t for t in transactions if t.get("status") == "disputed"]
    flagged = [t for t in transactions if t.get("is_flagged")]

    total_revenue_cents = sum(t.get("amount", 0) for t in succeeded)
    total_revenue_dollars = total_revenue_cents / 100

    # Build a plain-text list of flagged transactions and why, so the AI
    # has specifics to mention instead of just a count.
    flagged_lines = []
    for t in flagged:
        reasons = ", ".join(t.get("fraud_flags", []))
        amount = t.get("amount", 0) / 100
        flagged_lines.append(f"- ${amount:.2f} from {t.get('customer_email', 'unknown')} ({reasons})")
    flagged_text = "\n".join(flagged_lines) if flagged_lines else "None"

    # ---- Step 2: Build the prompt -----------------------------------------
    # A "prompt" is just the plain-English instructions + data we send Claude.
    # We're basically writing a note asking it to summarize these numbers.
    prompt = f"""You are writing a factual, professional summary of a merchant's
daily payment activity for a business dashboard.

Today's payment data:
- Successful payments: {len(succeeded)}
- Total revenue: ${total_revenue_dollars:.2f}
- Refunds: {len(refunded)}
- Disputes: {len(disputed)}
- Flagged (suspicious) transactions:
{flagged_text}

Write a direct, professional 2-3 sentence summary of today's activity.
State the facts plainly: revenue, transaction count, and any flags or
disputes. Do not add reassurance, hedging, or commentary like "nothing to
worry about" — just report what happened. Do not use markdown formatting,
headers, hashtags, or bullet points — plain sentences only. If there were
no transactions today, state that in one plain sentence with no extra
commentary."""

    # ---- Step 3: Send it to Claude and get the summary back ---------------
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=300,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    # Claude's reply comes back as a list of content blocks; for a plain
    # text response, the text we want is in the first block.
    return response.content[0].text