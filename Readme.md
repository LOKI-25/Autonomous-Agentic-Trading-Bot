# Autonomous Agentic Trading Bot & Institutional Risk Gatekeeper

A production-grade, autonomous AI trading system built using **LangGraph**, the **Model Context Protocol (MCP)**, and **Terraform** for AWS deployment. This project demonstrates an agentic workflow capable of complex financial analysis and execution, governed by a strict risk engine and a real-time, Human-in-the-Loop (HITL) reactive dashboard.

## 🏗 System Architecture

The project is architected as a decoupled multi-service system:
1.  **Agent Orchestrator (LangGraph & OpenAI)**: A stateful graph agent that reasons through market data, decides on trades, and maintains conversation memory via SQLite checkpointing.
2.  **Policy Engine (MCP Servers)**: Standardized integration with Alpha Vantage (Market Data), Alpaca (Brokerage), and a custom FastMCP Risk Gatekeeper enforcing institutional guardrails.
3.  **Middleware (FastAPI)**: An asynchronous bridge managing the graph execution, audit trails, real-time Server-Sent Events (SSE), and webhook coordination.
4.  **Manager Console (Angular 19)**: A high-performance, reactive dashboard for chat interactions, manual trade authorization, and portfolio monitoring.
5.  **Infrastructure as Code (AWS Terraform)**: Fully automated deployment pipeline provisioning EC2 instances, S3 static website hosting, and secure environment variable injection.

---

## 🚀 Key Features

### 1. LangGraph State Management & HITL
* **Asynchronous Resumption**: LLM execution is programmatically paused (`interrupt_before`) for high-value trades. The agent's state is serialized to a database, awaiting a manual "Approve" signal from the dashboard to resume execution on the exact thread.
* **Memory Checkpointing**: Maintains a continuous chat interface, allowing the AI to remember historical context and previous market analysis.

### 2. Institutional Governance (MCP)
* **Auto-Trade Ceiling**: Programmatically blocks any trade exceeding **$5,000** for manual review.
* **Restricted Asset List**: Hard-coded rejection of volatile assets (e.g., GME, AMC, DOGE).
* **Smart Analyst Memorandum**: Requires the LLM to generate a structured investment rationale and compliance rating before trade submission.

### 3. Financial Circuit Breaker
The system automatically suspends all trading activities if the daily portfolio loss exceeds a defined threshold:
$$Loss\% = \frac{CurrentEquity - PreviousClose}{PreviousClose} \times 100 \le -2.0\%$$

### 4. Infrastructure as Code (IaC)
* **One-Click Deployment**: A single bash script (`deploy.sh`) triggers Terraform to build, configure, and deploy the entire AWS architecture.
* **Dynamic Configuration**: Terraform auto-injects EC2 public IPs into the Angular environment files at build time for seamless API connectivity.

---

## 🛠 Tech Stack

* **Languages**: Python 3.12+, TypeScript
* **AI Framework**: LangGraph, LangChain, OpenAI (GPT-4o-mini), Model Context Protocol (MCP)
* **Backend**: FastAPI, Uvicorn, SQLite, `uv` (Rust-based Python package manager)
* **Frontend**: Angular 19, RxJS, Tailwind CSS
* **Infrastructure**: HashiCorp Terraform, AWS EC2, AWS S3
* **Data Providers**: Alpha Vantage API, Alpaca Markets API (Paper Trading)

---

## 📂 Project Structure

```text
Trading-bot/
├── agents/
│   └── graph_orchestrator.py # LangGraph definition and Multi-Server MCP client
├── servers/
│   └── risk_gatekeeper/      # MCP Policy Engine & FastAPI Middleware
├── frontend/
│   └── dashboard-ui/         # Angular 19 Reactive Dashboard
├── main.tf                   # Terraform Infrastructure definition
├── deploy.sh                 # Deployment automation script
└── terraform.tfvars          # (Ignored) Secure API keys for AWS injection
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