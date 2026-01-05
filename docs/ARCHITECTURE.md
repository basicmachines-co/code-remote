# Code Remote - Architecture

Technical documentation of the Code Remote system design.

## System Overview

Code Remote enables AI assistants to execute commands on your Mac by combining:

1. **MCP Server** - Exposes tools to AI clients via SSE (Server-Sent Events)
2. **WebSocket Relay** - Bridges AI requests to the Mac agent
3. **Mac Agent** - Executes commands and returns results

```
+------------------+     HTTPS/SSE      +-------------------+
|                  |<------------------>|                   |
|    AI Client     |    MCP Protocol    |   Unified Server  |
|    (iOS/Web)     |                    |    (Fly.io)       |
|                  |                    |                   |
+------------------+                    +-------------------+
                                              |       |
                                         SQLite    WebSocket
                                              |       |
                                              v       v
                                        +------------------+
                                        |                  |
                                        |    Mac Agent     |
                                        |    (Daemon)      |
                                        |                  |
                                        +------------------+
```

## Components

### Unified Server (`server/server.py`)

A single Starlette application that handles:

#### MCP Protocol (SSE Transport)

- **`GET /sse`** - SSE endpoint for MCP connection
- **`POST /messages`** - Message handling for MCP

Exposed tools:
- `run_shell_command` - Execute shell commands
- `read_file` - Read file contents
- `write_file` - Write to files
- `list_directory` - List directory contents
- `check_agent_status` - Verify agent connection

#### WebSocket Relay

- **`WS /ws/agent`** - WebSocket endpoint for Mac agent

Handles:
- Agent authentication via query parameter token
- Command dispatch to agent
- Result collection and storage

#### REST API

- **`GET /health`** - Health check with agent status
- **`GET /commands`** - List recent commands (authenticated)

### Mac Agent (`agent/agent.py`)

Headless Python daemon that:

1. Connects to server via WebSocket
2. Authenticates with token
3. Receives and executes commands
4. Returns results to server

#### Command Handlers

| Handler | Function |
|---------|----------|
| `execute_shell()` | Run shell commands via subprocess |
| `read_file()` | Read file contents with size limits |
| `write_file()` | Write content, create parent dirs |
| `list_dir()` | List directory with type/size info |

## Data Flow

### Command Execution Sequence

```
1. User → AI Client: "list my downloads folder"

2. AI Client → Server (/sse):
   {
     "method": "tools/call",
     "params": {
       "name": "list_directory",
       "arguments": {"path": "~/Downloads"}
     }
   }

3. Server:
   - Generate command ID
   - Insert into SQLite (status: pending)
   - Send to agent via WebSocket

4. Server → Agent (WebSocket):
   {
     "type": "execute",
     "id": "abc123",
     "command_type": "list_dir",
     "path": "~/Downloads"
   }

5. Agent:
   - Validate path is allowed
   - Execute list_dir()
   - Format results

6. Agent → Server (WebSocket):
   {
     "type": "result",
     "id": "abc123",
     "status": "completed",
     "output": "dir\t0\tDocuments\nfile\t1234\timage.png\n...",
     "exit_code": 0
   }

7. Server:
   - Update SQLite record
   - Return result to AI via SSE

8. Server → AI Client (/sse):
   {
     "content": [{"type": "text", "text": "dir\t0\tDocuments\n..."}]
   }

9. AI Client → User: "Your Downloads folder contains..."
```

## Security Model

### Authentication

All connections require a shared secret token:

```
AUTH_TOKEN (env var on server)
    |
    ├── WebSocket: ?token=xxx query parameter
    └── REST API: Authorization: Bearer xxx header
```

Token is:
- Set via Fly.io secrets
- 256-bit random value recommended
- Compared using constant-time comparison

### Agent Path Restrictions

The agent restricts file operations to safe directories:

```python
ALLOWED_PATHS = [
    Path.home(),     # /Users/username
    Path("/tmp"),
    Path("/var/tmp"),
]
```

All file operations verify paths resolve within allowed directories.

### Command Output Limits

- Maximum output size: 1MB
- Truncation with warning for larger outputs
- Prevents memory exhaustion

### Network Security

- All traffic over HTTPS/WSS
- Fly.io handles TLS termination
- No plaintext communication

## Database Schema

SQLite database at `/data/code_remote.db`:

```sql
CREATE TABLE commands (
    id TEXT PRIMARY KEY,           -- Random URL-safe ID
    type TEXT NOT NULL,            -- shell, read_file, write_file, list_dir
    status TEXT NOT NULL,          -- pending, running, completed, failed, timeout
    command TEXT,                  -- Shell command (for shell type)
    path TEXT,                     -- File/dir path (for file operations)
    content TEXT,                  -- File content (for write_file)
    working_dir TEXT,              -- Working directory (for shell)
    timeout INTEGER DEFAULT 60,    -- Command timeout in seconds
    output TEXT,                   -- Command output
    error TEXT,                    -- Error message
    exit_code INTEGER,             -- Process exit code
    created_at TEXT NOT NULL,      -- ISO timestamp
    started_at TEXT,               -- When agent started execution
    completed_at TEXT              -- When result was received
);

CREATE INDEX idx_commands_status ON commands(status);
CREATE INDEX idx_commands_created ON commands(created_at DESC);
```

## Connection Management

### Agent Reconnection

The agent implements automatic reconnection:

```python
while True:
    try:
        await connect_and_run()
    except ConnectionClosed:
        pass  # Normal disconnect
    except Exception as e:
        log_error(f"Connection error: {e}")

    await asyncio.sleep(RECONNECT_DELAY)  # 5 seconds
```

### Keep-Alive

WebSocket connections maintained via:

1. **Server-side**: Starlette's built-in ping/pong
2. **Agent-side**: Application-level ping every 25 seconds

### Pending Command Recovery

When agent connects, server sends any pending commands:

```python
async with db.execute(
    "SELECT * FROM commands WHERE status = 'pending' ORDER BY created_at ASC"
) as cursor:
    pending = await cursor.fetchall()

for row in pending:
    await manager.send_command(row["id"], {...})
```

## Deployment Considerations

### Single Machine vs Multi-Region

Current design assumes single machine (for WebSocket state):

- Agent connects to one machine
- Commands routed to that machine
- SQLite on local volume

For multi-region:
- Would need Redis/external queue
- Session affinity for WebSocket
- Shared database (e.g., Turso, Supabase)

### Resource Requirements

Minimal footprint:
- **CPU**: shared-cpu-1x sufficient
- **Memory**: 512MB handles typical load
- **Storage**: 1GB volume (commands are small)

### Monitoring Recommendations

1. **Health checks** - Monitor `/health` endpoint
2. **Log aggregation** - Fly.io logs or external service
3. **Agent uptime** - launchd keeps agent running
4. **Command latency** - Track time from created_at to completed_at
