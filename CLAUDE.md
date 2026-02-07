# Code Remote - Claude Instructions

## Project Overview

Code Remote is an MCP (Model Context Protocol) server that enables AI assistants to execute commands on a remote machine. It consists of two components:

1. **Server** (`server/`) - Deployed on Fly.io, handles MCP connections from AI clients and relays commands to the agent
2. **Agent** (`agent/`) - Runs on the user's machine, executes commands and returns results

## Security Configuration

The server supports Tailscale to restrict agent connections:

- `REQUIRE_PRIVATE_NETWORK=true` (default) - Only accepts agent connections from Tailscale IPs (100.64.0.0/10) or Fly.io internal IPs (fdaa::/16)
- `TAILSCALE_AUTHKEY` - Set as Fly.io secret (90-day max expiration)

See README.md for Tailscale setup instructions.

## Running the Agent

```bash
cd agent
./run.sh
```

The agent:
- Logs to `agent/logs/agent.log` with 10MB rotation (keeps 10 backups)
- Requires `RELAY_URL` and `AUTH_TOKEN` in `.env`

## Deploying Server Changes

```bash
cd server
fly deploy
```

## Key Files

| File | Purpose |
|------|---------|
| `server/server.py` | MCP server + WebSocket relay + Tailscale IP check |
| `server/start.sh` | Starts Tailscale daemon, then Python server |
| `server/Dockerfile` | Includes Tailscale installation |
| `agent/agent.py` | WebSocket client, command execution |
| `agent/run.sh` | Starts agent with log rotation |

## Development Notes

- Server uses Starlette + uvicorn
- Agent uses websockets library
- Both use Python 3.11+
- Use `uv` for Python package management

## Fly.io Commands

```bash
# Check logs
fly logs -a YOUR-APP-NAME

# SSH into server
fly ssh console -a YOUR-APP-NAME

# Check app status
fly status -a YOUR-APP-NAME

# Update secrets
fly secrets set KEY=value -a YOUR-APP-NAME
```
