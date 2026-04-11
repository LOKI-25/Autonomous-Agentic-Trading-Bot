# Autonomous Agentic Trading Bot & Institutional Risk Gatekeeper

A production-grade, human-in-the-loop (HITL) AI trading system built using the **Model Context Protocol (MCP)**. This project demonstrates an autonomous agent capable of financial analysis and execution, governed by a stateless risk engine and a real-time reactive dashboard.

## 🏗 System Architecture

The project is architected as a decoupled multi-service system:
1.  **Policy Engine (MCP Server)**: A Python-based FastMCP server that acts as the "Law of the Land," enforcing institutional guardrails and compliance tools.
2.  **Middleware (FastAPI)**: An asynchronous bridge managing the audit trail, real-time data streaming (SSE), and webhook coordination.
3.  **Manager Console (Angular 19)**: A high-performance, reactive dashboard built with TypeScript and Tailwind CSS for manual trade authorization and portfolio monitoring.

---

## 🚀 Key Features

### 1. Institutional Governance (MCP)
* **Auto-Trade Ceiling**: Programmatically blocks any trade exceeding **$5,000** for manual review.
* **Restricted Asset List**: Hard-coded rejection of volatile assets (e.g., GME, AMC, DOGE).
* **Smart Analyst Memorandum**: Requires the LLM to generate a structured 3-sentence investment rationale before trade submission.

### 2. Financial Circuit Breaker
The system automatically suspends all trading activities if the daily portfolio loss exceeds a defined threshold:
$$Loss\% = \frac{CurrentEquity - PreviousClose}{PreviousClose} \times 100 \le -2.0\%$$

### 3. Human-in-the-Loop (HITL) 
* **Asynchronous Resumption**: LLM execution is paused for high-value trades, awaiting a manual "Approve" signal from the dashboard.
* **Real-Time Sync**: Utilizes **Server-Sent Events (SSE)** to push updates from the backend to the UI in sub-seconds, eliminating polling.

---

## 🛠 Tech Stack

* **Languages**: Python 3.12+, TypeScript
* **AI Framework**: FastMCP (Model Context Protocol), Claude Code
* **Backend**: FastAPI, Uvicorn, SQLite
* **Frontend**: Angular 19, RxJS, Tailwind CSS
* **Tools**: Alpaca Markets API (Paper Trading)

---

## 📂 Project Structure

```text
Trading-bot/
├── servers/
│   └── risk_gatekeeper/      # MCP Policy Engine & FastAPI Middleware
├── frontend/
│   └── dashboard-ui/         # Angular 19 Reactive Dashboard
├── infrastructure/           # Terraform Cloud Configurations
├── config/                   # MCP settings.json & Environment variables
└── audit_log.db              # SQLite Persistent Audit Trail
```

---

## ⚙️ Installation & Setup

### Backend (Python)
1. Navigate to the server directory: `cd servers/risk_gatekeeper`
2. Install dependencies: `pip install -r requirements.txt`
3. Launch the Gatekeeper: `python risk_server.py`
4. Launch the Dashboard API: `python admin_dashboard.py`

### Frontend (Angular)
1. Navigate to the UI directory: `cd frontend/dashboard-ui`
2. Install packages: `npm install`
3. Initialize Tailwind: `npx tailwindcss init`
4. Start the server: `ng serve`

---

## 🛠 How It Works: The "Human-in-the-Loop" Lifecycle

This project implements a sophisticated asynchronous workflow that ensures no high-value trade is executed without explicit human authorization.

### Step 1: The Trade Initiation (MCP Layer)
* The user instructs the AI (e.g., Claude) to execute a trade.
* Claude calls the `verify_trade_risk` tool in **`risk_server.py`**.
* If the trade exceeds \$5,000, the server rejects auto-approval and requires a "Human-in-the-Loop" trigger.

### Step 2: AI Memorandum & Persistence
* Claude generates a professional **Investment Memorandum** (Rationale + Risk Rating).
* The tool `request_human_approval` saves the trade details, timestamp, and memorandum into the **`audit_log.db`** with a status of `PENDING`.

### Step 3: Real-Time UI Notification (The Webhook)
* **`risk_server.py`** sends a POST request to the **`/notify`** endpoint of the FastAPI dashboard.
* The FastAPI backend (`admin_dashboard.py`) triggers a **Server-Sent Event (SSE)**.
* The Angular frontend, listening to the `stream-trades` observable, instantly renders a new authorization card without a page refresh.

### Step 4: Human Authorization
* The Manager reviews the **AI Investment Memorandum** on the dashboard.
* Clicking **"Confirm Authorization"** sends a request to the `/approve/{id}` endpoint.
* The backend updates the SQLite record to `APPROVED` and broadcasts the update back to the UI.

### Step 5: Final Execution
* The AI agent (polling or via webhook) checks the status using the `check_approval_status` tool.
* Once the status is `APPROVED`, the agent proceeds to call the brokerage API (Alpaca) to finalize the order.