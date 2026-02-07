"""
Code Remote - Unified MCP + Relay Server

Single deployment that:
1. Exposes MCP tools to AI clients via SSE (/sse, /messages)
2. Accepts WebSocket connections from agent (/ws/agent)
3. Queues and routes commands between them
"""

import asyncio
import json
import os
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from contextlib import asynccontextmanager

import ipaddress

import aiosqlite
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/claude_remote.db")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "change-me-in-production")

# Ensure data directory exists
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

# =============================================================================
# Models
# =============================================================================

class CommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CommandType(str, Enum):
    SHELL = "shell"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_DIR = "list_dir"

# =============================================================================
# Database
# =============================================================================

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                command TEXT,
                path TEXT,
                content TEXT,
                working_dir TEXT,
                timeout INTEGER DEFAULT 60,
                output TEXT,
                error TEXT,
                exit_code INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at DESC)
        """)
        await db.commit()

# =============================================================================
# WebSocket Connection Manager (for Mac Agent)
# =============================================================================

class ConnectionManager:
    def __init__(self):
        self.agent_connection: Optional[WebSocket] = None
        
    async def connect_agent(self, websocket: WebSocket):
        await websocket.accept()
        self.agent_connection = websocket
        print(f"[{datetime.now(timezone.utc).isoformat()}] Agent connected")
        
    def disconnect_agent(self):
        self.agent_connection = None
        print(f"[{datetime.now(timezone.utc).isoformat()}] Agent disconnected")
        
    def is_agent_connected(self) -> bool:
        return self.agent_connection is not None
        
    async def send_command(self, command_id: str, command_data: dict) -> bool:
        if not self.agent_connection:
            return False
        try:
            await self.agent_connection.send_json({
                "type": "execute",
                "id": command_id,
                **command_data
            })
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False


manager = ConnectionManager()

# =============================================================================
# Command Execution (called by MCP tools)
# =============================================================================

async def execute_command(command_type: str, timeout: int = 60, **kwargs) -> str:
    """Submit a command and wait for results."""
    
    if not manager.is_agent_connected():
        return "Error: Mac agent is not connected. Please ensure the agent is running."
    
    command_id = secrets.token_urlsafe(12)
    now = datetime.now(timezone.utc).isoformat()
    
    # Insert command into database
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO commands (id, type, status, command, path, content, working_dir, timeout, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            command_id,
            command_type,
            CommandStatus.PENDING.value,
            kwargs.get("command"),
            kwargs.get("path"),
            kwargs.get("content"),
            kwargs.get("working_dir"),
            timeout,
            now
        ))
        await db.commit()
    
    # Send to agent
    success = await manager.send_command(command_id, {
        "command_type": command_type,
        "command": kwargs.get("command"),
        "path": kwargs.get("path"),
        "content": kwargs.get("content"),
        "working_dir": kwargs.get("working_dir"),
        "timeout": timeout
    })
    
    if not success:
        return "Error: Failed to send command to agent"
    
    # Update status to running
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE commands SET status = ?, started_at = ? WHERE id = ?",
            (CommandStatus.RUNNING.value, datetime.now(timezone.utc).isoformat(), command_id)
        )
        await db.commit()
    
    # Poll for completion
    for _ in range(timeout * 2 + 10):
        await asyncio.sleep(0.5)
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM commands WHERE id = ?", (command_id,)
            ) as cursor:
                row = await cursor.fetchone()
        
        if row and row["status"] in ("completed", "failed", "timeout"):
            output = row["output"] or ""
            error = row["error"] or ""
            exit_code = row["exit_code"]
            
            result_text = output
            if error:
                result_text += f"\n[stderr]: {error}"
            if exit_code is not None:
                result_text += f"\n[exit_code: {exit_code}]"
            return result_text.strip() or "(no output)"
    
    return "Command timed out waiting for response"

# =============================================================================
# MCP Server
# =============================================================================

mcp_server = Server("claude-remote")

@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="run_shell_command",
            description="Execute a shell command on the connected machine. Use this to run any terminal command.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Optional working directory (defaults to home). Use ~ for home directory."
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout in seconds (default 60)",
                        "default": 60
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="read_file",
            description="Read the contents of a file on the connected machine.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file. Use ~ for home directory."
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="write_file",
            description="Write content to a file on the connected machine. Creates parent directories if needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file. Use ~ for home directory."
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file"
                    }
                },
                "required": ["path", "content"]
            }
        ),
        Tool(
            name="list_directory",
            description="List contents of a directory on the connected machine.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the directory. Use ~ for home directory."
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="check_agent_status",
            description="Check if the agent is connected and ready to receive commands.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "run_shell_command":
            result = await execute_command(
                "shell",
                command=arguments["command"],
                working_dir=arguments.get("working_dir"),
                timeout=arguments.get("timeout", 60)
            )
            
        elif name == "read_file":
            result = await execute_command("read_file", path=arguments["path"])
            
        elif name == "write_file":
            result = await execute_command(
                "write_file",
                path=arguments["path"],
                content=arguments["content"]
            )
            
        elif name == "list_directory":
            result = await execute_command("list_dir", path=arguments["path"])
            
        elif name == "check_agent_status":
            if manager.is_agent_connected():
                result = "✓ Agent is connected and ready to receive commands"
            else:
                result = "✗ Agent is NOT connected - make sure it's running on the Mac"
                
        else:
            result = f"Unknown tool: {name}"
            
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]

# =============================================================================
# SSE Transport for MCP
# =============================================================================

sse = SseServerTransport("/messages")

async def handle_sse(request):
    async with sse.connect_sse(
        request.scope,
        request.receive,
        request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options()
        )


async def handle_messages(request):
    return await sse.handle_post_message(request.scope, request.receive, request._send)

# =============================================================================
# WebSocket Endpoint for Mac Agent
# =============================================================================

# Private network ranges for agent connections
TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")  # Tailscale CGNAT
FLYIO_NETWORK = ipaddress.ip_network("fdaa::/16")  # Fly.io private network
REQUIRE_PRIVATE_NETWORK = os.getenv("REQUIRE_PRIVATE_NETWORK", "true").lower() == "true"


def is_private_network_ip(ip_str: str) -> bool:
    """Check if IP is from Tailscale, Fly.io private network, or localhost."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback:
            return True
        if isinstance(ip, ipaddress.IPv4Address):
            return ip in TAILSCALE_NETWORK
        if isinstance(ip, ipaddress.IPv6Address):
            return ip in FLYIO_NETWORK
        return False
    except ValueError:
        return False


def get_client_ip(websocket: WebSocket) -> str:
    """Extract real client IP from headers or connection."""
    # Fly.io and most proxies use X-Forwarded-For
    forwarded = websocket.headers.get("x-forwarded-for", "")
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    # Fallback to direct connection
    client = websocket.client
    return client.host if client else ""


async def agent_websocket(websocket: WebSocket):
    # Check private network IP requirement (Tailscale or Fly.io internal)
    if REQUIRE_PRIVATE_NETWORK:
        client_ip = get_client_ip(websocket)
        if not is_private_network_ip(client_ip):
            print(f"[{datetime.now(timezone.utc).isoformat()}] Rejected agent connection from non-private IP: {client_ip}")
            await websocket.close(code=4003, reason="Forbidden: Private network required")
            return

    # Verify token from query params
    token = websocket.query_params.get("token")
    if not token or not secrets.compare_digest(token, AUTH_TOKEN):
        await websocket.close(code=4003, reason="Forbidden")
        return

    await manager.connect_agent(websocket)
    
    # Send any pending commands
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM commands WHERE status = 'pending' ORDER BY created_at ASC"
        ) as cursor:
            pending = await cursor.fetchall()
            
        for row in pending:
            await manager.send_command(row["id"], {
                "command_type": row["type"],
                "command": row["command"],
                "path": row["path"],
                "content": row["content"],
                "working_dir": row["working_dir"],
                "timeout": row["timeout"]
            })
            await db.execute(
                "UPDATE commands SET status = ?, started_at = ? WHERE id = ?",
                (CommandStatus.RUNNING.value, datetime.now(timezone.utc).isoformat(), row["id"])
            )
        await db.commit()
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "result":
                # Update command with result
                async with aiosqlite.connect(DATABASE_PATH) as db:
                    await db.execute("""
                        UPDATE commands
                        SET status = ?, output = ?, error = ?, exit_code = ?, completed_at = ?
                        WHERE id = ?
                    """, (
                        data.get("status", "completed"),
                        data.get("output"),
                        data.get("error"),
                        data.get("exit_code"),
                        datetime.now(timezone.utc).isoformat(),
                        data.get("id")
                    ))
                    await db.commit()
                print(f"[{datetime.now(timezone.utc).isoformat()}] Command {data.get('id')} completed")
                
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect_agent()
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect_agent()

# =============================================================================
# REST Endpoints
# =============================================================================

async def health(request):
    return JSONResponse({
        "status": "ok",
        "agent_connected": manager.is_agent_connected(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


async def get_commands(request):
    """List recent commands (for debugging)"""
    # Simple auth check via header
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not secrets.compare_digest(auth[7:], AUTH_TOKEN):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    limit = int(request.query_params.get("limit", "20"))
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM commands ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    
    return JSONResponse([
        {
            "id": row["id"],
            "type": row["type"],
            "status": row["status"],
            "command": row["command"],
            "path": row["path"],
            "output": row["output"][:500] if row["output"] else None,
            "error": row["error"],
            "exit_code": row["exit_code"],
            "created_at": row["created_at"],
        }
        for row in rows
    ])

# =============================================================================
# Starlette App
# =============================================================================

@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield


app = Starlette(
    debug=False,
    lifespan=lifespan,
    routes=[
        # Health check
        Route("/health", endpoint=health),
        
        # MCP SSE endpoints
        Route("/sse", endpoint=handle_sse),
        Route("/messages", endpoint=handle_messages, methods=["POST"]),
        
        # REST API (for debugging)
        Route("/commands", endpoint=get_commands),
        
        # WebSocket for Mac agent
        WebSocketRoute("/ws/agent", endpoint=agent_websocket),
    ]
)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
