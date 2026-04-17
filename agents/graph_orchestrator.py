from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode
import uuid
from datetime import datetime
import httpx
import os
import json
import asyncio
from pathlib import Path

from servers.risk_gatekeeper.risk_server import get_compliance_manual


def load_service_config() -> dict:
    """Load service endpoints from environment variables or a config file."""
    # Optional .env support
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    base_dir = Path(__file__).resolve().parents[1]
    config_file = Path(os.getenv("SERVICE_CONFIG_PATH", base_dir / "config" / "service_config.json"))

    default_config = {
        "vantage": {"url": os.getenv("VANTAGE_URL", "http://vantage-mcp-server")},
        "alpaca": {"url": os.getenv("ALPACA_URL", "http://alpaca-mcp-server")},
        "risk_gatekeeper": {"url": os.getenv("RISK_GATEKEEPER_URL", "http://localhost:8000")},
        "webhook": {"url": os.getenv("WEBHOOK_URL", "http://localhost:8000/webhook")},
    }

    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[LangGraph] Warning: failed to load config file {config_file}: {exc}")

    return default_config


service_config = load_service_config()

# --- 1. Bind MCP Tools for the Agent ---

base_dir = Path(__file__).resolve().parents[1]
venv_python = str(base_dir / "venv" / "bin" / "python3")
risk_server_path = str(base_dir / "servers" / "risk_gatekeeper" / "risk_server.py")

mcp_config = {
    "vantage": {
      "transport": "stdio",
      "command": "uvx",
      "args": [ "--from", "marketdata-mcp-server", "marketdata-mcp", "S7BD5372Z7Q0JRKQ" ]
    },
    "alpaca": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "PKL33CSLBDT32GPFPJSAZGZDG2",
        "ALPACA_SECRET_KEY": "9LL7pvNVkWyQhJ3aZ5JpSpy9MVThG3D4YMe5CTPYA4Po"
      }
    },
    "risk_gatekeeper": {
      "transport": "stdio",
      "command": venv_python,
      "args": [
        risk_server_path
      ],
      "env": {
        "GMAIL_USER": "dumbbu123@gmail.com",
        "GMAIL_APP_PASS": "lkjt uosk sian hnrn",
        "MANAGER_EMAIL": "dumbbu123@gmail.com"
        }
    }
  
}

mcp_client = MultiServerMCPClient(mcp_config)

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    trade_id: str

_cached_workflow = None

async def get_workflow() -> StateGraph:
    """Asynchronously builds and returns the LangGraph workflow.
       This prevents 'event loop is already running' errors during Uvicorn startup.
    """
    global _cached_workflow
    if _cached_workflow is not None:
        return _cached_workflow

    # --- 1. Safely resolve the async get_tools() coroutine ---
    tools = await mcp_client.get_tools()

    for tool in tools:
        tool.handle_tool_error = True

    # --- 2. Define the Agent ---
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=5)
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)

    # --- 3. Define the Nodes ---
    def agent_node(state: AgentState):
        messages = list(state["messages"])
        if not any(isinstance(msg, SystemMessage) for msg in messages):
            manual = get_compliance_manual()
            prompt_content = f"""You are an autonomous financial trading assistant.
Your primary directive is to execute trades, provide market analysis, and adhere strictly to the Institutional Compliance Manual below.

--- INSTITUTIONAL COMPLIANCE MANUAL ---
{manual}
---------------------------------------

CORE BEHAVIORS:
- DOMAIN RESTRICTION: Politely refuse to answer general knowledge or off-topic questions. 
- ASSET RESOLUTION: Autonomously resolve company names to ticker symbols without asking, unless ambiguous.
- ANALYSIS & REPORTS: If the user asks for market analysis, news, sentiment, or a detailed report, you MUST use the Alpha Vantage tools. Do not use Alpaca for deep market research. Don't use any tools releated to cryptocurrency.
- TOOL USAGE: Rely entirely on your provided tools. Read their descriptions carefully to understand the required order of operations.
- PRICING: You MUST ALWAYS fetch the live asset price using market data tools (e.g., get_stock_latest_quote) BEFORE calling verify_trade_risk. NEVER assume, guess, or use 0 for the price.
- COMPLIANCE FIRST: You are STRICTLY FORBIDDEN from executing any live trades before verifying risk and receiving an 'APPROVED' signal.
- EXTERNAL SCHEMAS: For external market data tools, ensure you follow their specific nested JSON schemas if required (e.g., wrapping inputs in an `arguments` object).
- MANAGER OVERRIDES: Immediately obey any human manager APPROVED or REJECTED override messages."""
            sys_msg = SystemMessage(content=prompt_content)
            messages.insert(0, sys_msg)

        result = llm_with_tools.invoke(messages)
        return {"messages": [result]}

    tool_node = ToolNode(tools)

    def human_approval_node(state: AgentState):
        print(f"--- PAUSING FOR HUMAN APPROVAL ---")
        print(f"Trade {state['trade_id']} is waiting for a manager to approve/reject.")
        print(f"----------------------------------")
        return {}

    # --- 4. Build the Routing & Graph ---
    def route_after_agent(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    def should_continue(state: AgentState) -> str:
        for msg in reversed(state["messages"]):
            if not isinstance(msg, ToolMessage):
                break
            if msg.name == "request_human_approval":
                return "pause_for_approval"
        return "agent"

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("pause_for_approval", human_approval_node)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "end": END})
    workflow.add_conditional_edges("tools", should_continue, {"pause_for_approval": "pause_for_approval", "agent": "agent"})
    workflow.add_edge("pause_for_approval", "agent")

    _cached_workflow = workflow
    return workflow

# --- Export the Graph ---
if __name__ == "__main__":
    async def generate_flowchart():
        workflow = await get_workflow()
        app_graph = workflow.compile()
        print("[LangGraph] Workflow compiled and ready.")
        try:
            image_bytes = app_graph.get_graph().draw_mermaid_png()
            output_path = Path(__file__).parent / "graph_flowchart.png"
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            print(f"[LangGraph] Flowchart saved to {output_path}")
        except Exception as e:
            print(f"[LangGraph] Could not generate flowchart. Error: {e}")
            
    asyncio.run(generate_flowchart())
