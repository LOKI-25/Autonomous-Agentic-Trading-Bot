from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sqlite3
import json
import asyncio
import uuid
from typing import Optional

import sys
from pathlib import Path
import os
sys.path.append(str(Path(__file__).resolve().parents[2]))

from agents.graph_orchestrator import get_workflow
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

app = FastAPI(title="Autonomous Trading Orchestrator & Dashboard")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

new_trade_event = asyncio.Event()

def print_graph_event(event):
    """Helper to pretty-print graph events to the terminal."""
    def get_server_name(tool_name: str) -> str:
        """Maps a tool name back to its parent MCP Server."""
        if tool_name in ["verify_trade_risk", "request_human_approval", "check_approval_status"]:
            return "Risk Gatekeeper"
        elif tool_name.startswith("TOOL_"):  # marketdata-mcp-server wrappers
            return "Alpha Vantage"
        return "Alpaca"

    for node_name, node_state in event.items():
        print(f"\n--- [{node_name.upper()}] ---")
        if isinstance(node_state, dict) and "messages" in node_state:
            messages = node_state["messages"]
            if not isinstance(messages, list):
                messages = [messages]
            for msg in messages:
                if isinstance(msg, AIMessage):
                    if msg.content:
                        print(f"🤖 AI: {msg.content}")
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for call in msg.tool_calls:
                            server = get_server_name(call['name'])
                            print(f"⚙️  CALLING TOOL: {call['name']} [{server}] | args: {call['args']}")
                elif isinstance(msg, ToolMessage):
                    server = get_server_name(msg.name)
                    formatted_content = str(msg.content)
                    if isinstance(msg.content, list):
                        blocks = []
                        for block in msg.content:
                            if isinstance(block, dict) and "text" in block:
                                text_val = block["text"]
                                try:
                                    parsed = json.loads(text_val)
                                    blocks.append(json.dumps(parsed, indent=2))
                                except Exception:
                                    blocks.append(str(text_val))
                            else:
                                blocks.append(str(block))
                        formatted_content = "\n".join(blocks)
                    elif isinstance(msg.content, str):
                        try:
                            parsed = json.loads(msg.content)
                            formatted_content = json.dumps(parsed, indent=2)
                        except Exception:
                            formatted_content = msg.content
                    print(f"🛠️  TOOL RESULT ({msg.name} @ {server}):\n{formatted_content}")
                elif isinstance(msg, HumanMessage):
                    print(f"👤 HUMAN: {msg.content}")
                else:
                    print(f"📝 {type(msg).__name__}: {msg.content}")

# Use your verified absolute path
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "audit_log.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

@app.on_event("startup")
async def startup_events():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_threads (id TEXT PRIMARY KEY, title TEXT, messages TEXT)''')
    conn.commit()
    conn.close()
    # Pre-warm the MCP tools and graph on server startup
    await get_workflow()

@app.get("/")
def read_root():
    return {"status": "Online", "message": "Access /docs for the Manager Interface"}

class AgentInput(BaseModel):
    query: str
    thread_id: Optional[str] = None

class ChatThreadData(BaseModel):
    id: str
    title: str
    messages: list

@app.post("/sync-chat")
def sync_chat(thread: ChatThreadData):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO chat_threads (id, title, messages) VALUES (?, ?, ?)",
                 (thread.id, thread.title, json.dumps(thread.messages)))
    conn.commit()
    conn.close()
    return {"status": "synced"}

@app.get("/chat-threads")
def get_chat_threads():
    conn = get_db_connection()
    threads = conn.execute("SELECT id, title, messages FROM chat_threads").fetchall()
    conn.close()
    return [{"id": t["id"], "title": t["title"], "messages": json.loads(t["messages"])} for t in threads]

@app.post("/trade")
async def initiate_trade(agent_input: AgentInput):
    """Entry point for the Autonomous LangGraph Agent."""
    print(f"\n{'='*60}\n👤 NEW REQUEST: {agent_input.query}\n{'='*60}")
    # Use the provided thread_id to continue a conversation, or create a new one
    trade_id = agent_input.thread_id or str(uuid.uuid4())[:8]
    # Add a recursion limit so the AI can never infinite-loop and hang the server
    config = {"configurable": {"thread_id": trade_id}, "recursion_limit": 15}
    
    # Pass the input as a dict so LangGraph's reducer appends the message to history
    input_state = {"messages": [HumanMessage(content=agent_input.query)], "trade_id": trade_id}
    
    try:
        async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
            await checkpointer.setup()
            workflow = await get_workflow()
            app_graph = workflow.compile(checkpointer=checkpointer, interrupt_before=["pause_for_approval"])
            
            # Run the graph until completion or breakpoint
            async for event in app_graph.astream(input_state, config):
                print_graph_event(event)
                
            state = await app_graph.aget_state(config)
            if state.next and "pause_for_approval" in state.next:
                return {"message": "Trade paused for human approval.", "trade_id": trade_id, "status": "pending_approval"}
            
            # If the graph finished, return the agent's final message.
            last_message = state.values["messages"][-1]
            if isinstance(last_message, AIMessage):
                return {"message": last_message.content, "trade_id": trade_id, "status": "completed"}

        # Fallback for unexpected end states
        return {"message": "Trade process concluded.", "trade_id": trade_id, "status": "executed"}
    except Exception as e:
        import traceback
        print("--- AGENT ERROR ---")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pending-trades")
def get_pending_trades():
    """Fetch trades including the AI-generated Memorandum."""
    conn = get_db_connection()
    trades = conn.execute("SELECT id, timestamp, symbol, amount, status, reason, memorandum FROM trade_approvals WHERE status = 'PENDING'").fetchall()
    conn.close()
    return [dict(trade) for trade in trades]

@app.get("/stream-trades")
async def stream_trades():
    async def event_generator():
        while True:
            conn = get_db_connection()
            trades = conn.execute("SELECT id, timestamp, symbol, amount, status, reason,memorandum FROM trade_approvals WHERE status = 'PENDING'").fetchall()
            conn.close()
            
            # Package trades
            latest_data = {
                "trades": [dict(trade) for trade in trades]
            }
            
            yield f"data: {json.dumps(latest_data)}\n\n"

            # Wait until a new trade is added or approved before sending the next update
            await new_trade_event.wait()
            new_trade_event.clear()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/approve/{trade_id}")
async def approve_trade(trade_id: str):
    """Manager override: Set trade to APPROVED."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trade_approvals SET status = 'APPROVED' WHERE id = ?", (trade_id,))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Trade ID not found")
    conn.commit()
    conn.close()
    new_trade_event.set()
    
    # --- WEBHOOK RESUME SIGNAL ---
    config = {"configurable": {"thread_id": trade_id}}
    print(f"--> Resuming graph for trade {trade_id} (APPROVED)...")
    # We inject a message back into the agent's history to inform it of the approval
    # This is a more robust way to resume than just changing a boolean flag.
    resume_message = HumanMessage(content="SYSTEM OVERRIDE: The manager has explicitly APPROVED the pending trade you just submitted. You MUST now proceed immediately to execute it using your brokerage execution tools. DO NOT call verify_trade_risk again.")
    
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        workflow = await get_workflow()
        app_graph = workflow.compile(checkpointer=checkpointer, interrupt_before=["pause_for_approval"])
        async for event in app_graph.astream({"messages": [resume_message]}, config):
            print_graph_event(event)
            
    return {"message": f"Trade {trade_id} APPROVED by Manager."}

@app.post("/reject/{trade_id}")
async def reject_trade(trade_id: str):
    """Manager override: Set trade to REJECTED."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trade_approvals SET status = 'REJECTED' WHERE id = ?", (trade_id,))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Trade ID not found")
    conn.commit()
    conn.close()
    new_trade_event.set()
    
    # --- WEBHOOK RESUME SIGNAL ---
    config = {"configurable": {"thread_id": trade_id}}
    print(f"--> Resuming graph for trade {trade_id} (REJECTED)...")
    resume_message = HumanMessage(content="SYSTEM OVERRIDE: The manager has explicitly REJECTED the pending trade you just submitted. You MUST output a final plain text message to the user explaining the rejection. DO NOT call any more tools.")

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        workflow = await get_workflow()
        app_graph = workflow.compile(checkpointer=checkpointer, interrupt_before=["pause_for_approval"])
        async for event in app_graph.astream({"messages": [resume_message]}, config):
            print_graph_event(event)
            
    return {"message": f"Trade {trade_id} REJECTED by Manager."}

@app.post("/notify")
def notify_update():
    """Webhook for the MCP server to trigger an SSE UI update."""
    new_trade_event.set()
    return {"message": "Update triggered"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_dashboard:app", host="0.0.0.0", port=8000, reload=True)