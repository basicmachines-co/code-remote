# Code Remote

Execute commands on your machine from any MCP-compatible AI client.

Code Remote bridges MCP (Model Context Protocol) with your local machine, enabling AI assistants to run shell commands, read/write files, and explore your filesystem - all from your phone or any web browser.

## Architecture

**Cloud/Self-Hosted Setup:**
```
+----------------+          +-------------------+          +----------------+
|                |   SSE    |                   |    WS    |                |
|   AI Client    |<-------->|  Server (Cloud)   |<-------->|     Agent      |
|   (MCP)        |   MCP    |                   |  Relay   |   (Daemon)     |
+----------------+          +-------------------+          +----------------+
```

**Local Setup with ngrok (everything on one machine):**
```
+----------------+          +-------------------+          +---------------------------+
|                |  HTTPS   |                   |          |      Your Machine         |
|   AI Client    |--------->|   ngrok tunnel    |--------->| +-------+     +-------+   |
|   (MCP)        |          |                   |          | |Server |<--->| Agent |   |
+----------------+          +-------------------+          | +-------+     +-------+   |
                                                           +---------------------------+
```

**Data Flow:**
1. You chat with an AI assistant (Claude.ai, etc.)
2. The AI calls MCP tools (run_shell_command, read_file, etc.)
3. Server queues commands and sends them to connected agent via WebSocket
4. Agent executes commands on your machine and returns results
5. Results flow back to the AI through SSE

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager (required for agent)
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Python 3.10+** - For running the agent
- **Docker** - For self-hosted server deployment (Options A & B)
- **Fly.io CLI** - For managed deployment (Option C only)

## Quick Start

Choose your deployment method:

### Option A: Local with ngrok (Simplest)

Run everything locally with ngrok for HTTPS tunneling. No cloud deployment needed.

```bash
# Terminal 1: Start the server
export AUTH_TOKEN=$(openssl rand -hex 32)
echo "AUTH_TOKEN=$AUTH_TOKEN" > .env
docker-compose up -d

# Terminal 2: Start ngrok tunnel
ngrok http 8080
# Note the https://xxx.ngrok-free.app URL

# Terminal 3: Start the agent (connects locally)
cd agent
uv venv && uv pip install -r requirements.txt
source .venv/bin/activate
export AUTH_TOKEN=$(cat ../.env | cut -d= -f2)
export RELAY_URL=ws://localhost:8080/ws/agent
python agent.py
```

Add to your MCP client:
- **URL:** `https://xxx.ngrok-free.app/sse` (your ngrok URL)

**Note:** Free ngrok tier gives a random URL that changes on restart. Paid plans offer stable subdomains.

### Option B: Docker + Reverse Proxy (Self-Hosted)

Run the server on your own infrastructure with a proper domain.

```bash
# 1. Generate an auth token
export AUTH_TOKEN=$(openssl rand -hex 32)
echo "AUTH_TOKEN=$AUTH_TOKEN" > .env

# 2. Start the server
docker-compose up -d

# 3. Set up HTTPS (see HTTPS Setup section below)
```

### Option C: Fly.io (Managed)

Deploy to Fly.io for automatic HTTPS and global availability.

```bash
cd server

# Edit fly.toml and set your app name
# Change: app = "YOUR-APP-NAME"
# To:     app = "yourname-code-remote"

fly launch --name YOUR-APP-NAME --region dfw --no-deploy
fly volumes create code_remote_data --size 1 --region dfw
fly secrets set AUTH_TOKEN=$(openssl rand -hex 32)
fly deploy
```

Your URLs will be:
- **MCP endpoint:** `https://YOUR-APP-NAME.fly.dev/sse`
- **WebSocket:** `wss://YOUR-APP-NAME.fly.dev/ws/agent`

### Install the Agent (Options B & C)

**Native agent** (runs directly on your machine):
```bash
cd agent
./setup.sh
# Enter your relay URL (e.g., wss://your-server.example.com/ws/agent)
# Enter your auth token
./run.sh
```

**Sandboxed agent** (runs in Docker container):
```bash
# Run full stack with containerized agent
docker-compose --profile full up -d
```

The sandboxed agent runs as a non-root user in an isolated Linux environment with common development tools (git, curl, vim, ripgrep, etc.). Files are restricted to `/home/agent/workspace` inside the container.

### Connect Your AI Client

Add to your MCP client settings:
- **URL:** `https://your-server.example.com/sse`

For Claude.ai: Settings > Connectors > MCP

## Customization

When deploying your own instance:

| File | What to Change |
|------|----------------|
| `server/fly.toml` | `app = "YOUR-APP-NAME"` |

The `setup.sh` script will prompt for your relay URL and auth token, creating the `.env` file automatically. You only need to edit `fly.toml` before deploying.

## Available Tools

| Tool | Description |
|------|-------------|
| `run_shell_command` | Execute any shell command |
| `read_file` | Read file contents |
| `write_file` | Write content to a file |
| `list_directory` | List directory contents |
| `check_agent_status` | Verify agent is connected |

## Documentation

- [Setup Guide](docs/SETUP.md) - Complete installation instructions
- [Deployment](docs/DEPLOYMENT.md) - Fly.io deployment and management
- [Architecture](docs/ARCHITECTURE.md) - System design and security

## HTTPS Setup

MCP clients typically require HTTPS. If you're self-hosting with Docker, you'll need a reverse proxy. Here's a simple example with Caddy:

```bash
# Install Caddy (https://caddyserver.com/docs/install)
# Create Caddyfile:
cat > Caddyfile << 'EOF'
your-domain.com {
    reverse_proxy localhost:8080
}
EOF

# Run Caddy (automatically provisions TLS via Let's Encrypt)
caddy run
```

For other options:
- **nginx**: Use certbot for Let's Encrypt certificates
- **Traefik**: Built-in ACME support for automatic TLS
- **Cloudflare Tunnel**: Free option that handles TLS for you

## Security

- Token-based authentication between all components
- Agent restricts file access to home directory, /tmp, /var/tmp
- All traffic encrypted via HTTPS/WSS
- Commands logged to SQLite for audit trail
- **Sandboxed mode**: Run the agent in a Docker container for full isolation
- **Tailscale integration**: Restrict agent connections to your private Tailscale network

### Tailscale Setup (Recommended)

For additional security, you can configure the server to only accept agent connections from your Tailscale network. This ensures that even if your AUTH_TOKEN is compromised, only devices on your tailnet can connect as an agent.

**1. Generate a Tailscale auth key:**

Go to https://login.tailscale.com/admin/settings/keys and create a new auth key:
- Check "Reusable" (so the server can reconnect after restarts)
- Optionally check "Ephemeral"
- Note: Keys expire after 90 days maximum

**2. Set the auth key as a Fly.io secret:**

```bash
fly secrets set TAILSCALE_AUTHKEY=tskey-auth-xxxxx -a YOUR-APP-NAME
```

**3. Deploy the server:**

```bash
cd server
fly deploy
```

**4. Configure the agent to connect via Tailscale:**

After deployment, find your server's Tailscale IP in the Fly.io logs:
```bash
fly logs -a YOUR-APP-NAME | grep "peerapi: serving"
# Look for: peerapi: serving on http://100.x.x.x:xxxxx
```

Update your agent's `.env`:
```bash
RELAY_URL=ws://100.x.x.x:8080/ws/agent
```

**Architecture with Tailscale:**
```
+----------------+          +-------------------+          +----------------+
|                |   SSE    |                   |    WS    |                |
|   AI Client    |<-------->|  Server (Cloud)   |<-------->|     Agent      |
|   (MCP)        |  HTTPS   |  + Tailscale      | Tailscale|   (Daemon)     |
+----------------+          +-------------------+          +----------------+
                                    |
                            Only accepts agent
                            connections from
                            Tailscale IPs
                            (100.64.0.0/10)
```

**Note:** The MCP endpoint remains publicly accessible (for Claude.ai), but agent connections are restricted to your Tailscale network.

### Disabling Tailscale Requirement

To allow agent connections from any IP (less secure):
```bash
fly secrets set REQUIRE_PRIVATE_NETWORK=false -a YOUR-APP-NAME
```

## Project Structure

```
code-remote/
├── docker-compose.yml   # Self-hosted deployment
├── .env.example         # Environment template
│
├── server/              # Server (Docker or Fly.io)
│   ├── server.py        # Combined MCP + Relay server
│   ├── start.sh         # Startup script (Tailscale + server)
│   ├── Dockerfile
│   ├── fly.toml         # Fly.io config (change app name)
│   └── requirements.txt
│
├── agent/               # Agent (native or containerized)
│   ├── agent.py         # WebSocket client daemon
│   ├── Dockerfile       # Sandboxed Linux agent
│   ├── requirements.txt
│   ├── setup.sh         # Setup script (prompts for URL)
│   ├── run.sh           # Run script (with log rotation)
│   ├── logs/            # Agent logs (auto-rotated)
│   └── com.code.remote-agent.plist
│
└── docs/                # Documentation
    ├── SETUP.md
    ├── DEPLOYMENT.md
    └── ARCHITECTURE.md
```

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE).

## Author

Drew Cain ([@groksrc](https://github.com/groksrc))
