import os
import sqlite3
import uuid
import smtplib
from datetime import datetime
from email.message import EmailMessage
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import urllib.request
import mcp.types as types
import asyncio
import json
from pathlib import Path


# Load secrets from .env file
load_dotenv()

# Initialize FastMCP Server
mcp = FastMCP("Gatekeeper")

# --- DATABASE LOGIC ---
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "audit_log.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    curr = conn.cursor()
    curr.execute('''CREATE TABLE IF NOT EXISTS trade_approvals 
                 (id TEXT PRIMARY KEY, timestamp TEXT, symbol TEXT, 
                  amount REAL, status TEXT, reason TEXT, memorandum TEXT)''')
    conn.commit()
    conn.close()

# Ensure database is created automatically when server starts
init_db()

# --- NOTIFICATION LOGIC (Step 1.4) ---
def send_approval_email(approval_id, symbol, amount, investment_memo):
    sender = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASS")
    manager = os.getenv("MANAGER_EMAIL")
    
    if not all([sender, password, manager]):
        print("Email credentials missing in .env. Skipping notification.")
        return

    msg = EmailMessage()
    msg.set_content(f"ACTION REQUIRED: Trade {approval_id} for {symbol} (${amount:,.2f}) is pending review.\n\nInvestment Memorandum:\n{investment_memo}")
    msg['Subject'] = f"Compliance Alert for {symbol}: Trade ID {approval_id}"
    msg['From'] = sender
    msg['To'] = manager

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.send_message(msg)
    except Exception as e:
        print(f"SMTP Error: {e}")

# --- MCP RESOURCES ---
@mcp.resource("compliance://manual")
def get_compliance_manual() -> str:
    """The 'Single Source of Truth' for AI behavior"""
    return """
    INSTITUTIONAL POLICY v2026:
    - MAXIMUM AUTO-TRADE: $5,000. If a trade exceeds this amount, you MUST call the `request_human_approval` tool and provide a detailed investment memorandum.
    - RESTRICTED ASSETS: GME, AMC, DOGE.
    - CIRCUIT BREAKER: No trading if daily portfolio loss > 2%. you can get to know it by calling the `verify_trade_risk` tool.
    """

# --- MCP TOOLS ---
@mcp.tool()
def verify_trade_risk(symbol: str, price: float, quantity: int = 1, current_daily_loss_pct: float = 0.0) -> str:
    """
    MANDATORY COMPLIANCE CHECK: You are STRICTLY FORBIDDEN from executing any trade (buy/sell)
    via your brokerage tools without calling this tool first.

    Returns:
        A canonical status string in one of: APPROVED, PENDING, REJECTED.
        The caller may include contextual detail after the status.
    """
    amount = price * quantity
    symbol = symbol.upper()
    restricted = ["GME", "AMC", "DOGE"]

    if symbol in restricted:
        return f"REJECTED: {symbol} is on the Restricted Asset List."

    if current_daily_loss_pct < -2.0:
        return f"REJECTED: Daily loss of {current_daily_loss_pct:.2f}% exceeds circuit breaker threshold."

    if amount > 5000:
        return f"PENDING: Trade for {symbol} (${amount:,.2f}) exceeds auto-limit. Human approval required."

    conn = sqlite3.connect(DB_PATH)
    curr = conn.cursor()
    approval_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().isoformat()
    curr.execute("""
        INSERT INTO trade_approvals (id, timestamp, symbol, amount, status, reason, memorandum)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (approval_id, timestamp, symbol, amount, "APPROVED", "Auto-approved under threshold", "Auto-approved by policy. No memo required."))
    conn.commit()
    conn.close()

    return "APPROVED: Trade meets all standard compliance criteria."

@mcp.tool()
async def request_human_approval(symbol: str, amount: float, reason: str, investment_memo: str) -> str:
    """
    Submit a trade for manual review. You MUST call this if `verify_trade_risk` returns 'PENDING'.
    You CANNOT execute the trade until this tool returns an 'APPROVED' decision.
    
    Args:
        symbol: The ticker symbol of the asset being traded .
        amount: The total monetary value of the trade in USD.
        reason: A short explanation of why the trade requires manual review.
        investment_memo: The generated professional 3-sentence memorandum.

    IMPORTANT INSTRUCTIONS: 
    Before calling this tool, you must generate a professional 3-sentence 'Investment Memorandum' 
    based on the trade details. Include a 'Risk Rating' based on standard Institutional Policy. 
    Pass this generated text into the `investment_memo` parameter.
    """
    approval_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().isoformat()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        curr = conn.cursor()
        curr.execute("""
            INSERT INTO trade_approvals (id, timestamp, symbol, amount, status, reason, memorandum) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (approval_id, timestamp, symbol.upper(), amount, "PENDING", reason, investment_memo))
        conn.commit()
        conn.close()
        
        send_approval_email(approval_id, symbol, amount, investment_memo)
        
        try:
            dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:8000")
            req = urllib.request.Request(f"{dashboard_url}/notify", method="POST")
            urllib.request.urlopen(req, timeout=2)
        except Exception as e:
            print(f"UI notification failed: {e}")
        return f"PAUSED: Request {approval_id} submitted. The investment memorandum has been saved. The system will resume automatically upon manager approval."


    except Exception as e:
        return f"Database error: {str(e)}"

@mcp.tool()
def check_approval_status(approval_id: str) -> str:
    """Step 3: Resume logic to check if human clicked 'Approve'."""
    conn = sqlite3.connect(DB_PATH)
    curr = conn.cursor()
    curr.execute("SELECT status FROM trade_approvals WHERE id = ?", (approval_id,))
    result = curr.fetchone()
    conn.close()
    
    return result[0] if result else "NOT_FOUND"

if __name__ == "__main__":
    mcp.run()