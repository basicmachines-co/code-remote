# Code Remote - Setup Guide

Complete instructions for setting up Code Remote from scratch.

## Prerequisites

### Required
- **[uv](https://docs.astral.sh/uv/)** - Fast Python package manager
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Python 3.10+** - For running the agent
- **Fly.io CLI** - For deploying the server ([Install](https://fly.io/docs/hands-on/install-flyctl/))
- **Fly.io Account** - Free tier works fine ([Sign up](https://fly.io/))
- **MCP-compatible AI client** - Claude.ai, or any client supporting MCP

### Recommended
- **macOS** - Agent is designed for Mac (can be adapted for Linux)
- **Homebrew** - For installing dependencies on Mac

## Step 1: Deploy the Server

The server runs on Fly.io and handles:
- MCP protocol (SSE transport) for AI clients
- WebSocket relay for the Mac agent
- Command queue persistence (SQLite)

### First-time Deployment

```bash
# Navigate to server directory
cd server

# Login to Fly.io (if not already)
fly auth login

# Launch the app (creates fly.toml if needed)
fly launch --name your-app-name --region dfw --no-deploy

# Create a volume for SQLite persistence
fly volumes create code_remote_data --size 1 --region dfw

# Set the auth token (save this - you'll need it for the agent)
export AUTH_TOKEN=$(openssl rand -hex 32)
echo "Your AUTH_TOKEN: $AUTH_TOKEN"
fly secrets set AUTH_TOKEN=$AUTH_TOKEN

# Deploy
fly deploy
```

### Verify Deployment

```bash
# Check health
curl https://your-app-name.fly.dev/health

# Should return:
# {"status":"ok","agent_connected":false,"timestamp":"..."}
```

## Step 2: Install the Agent

The agent runs on your Mac and executes commands from AI assistants.

### Automatic Setup

```bash
# Navigate to agent directory
cd agent

# Run setup script
./setup.sh
```

The script will:
1. Create a Python virtual environment
2. Install dependencies
3. Prompt for your relay URL and auth token
4. Create `.env` configuration file

### Manual Setup

If you prefer manual setup:

```bash
# Create virtual environment with uv
uv venv .venv
source .venv/bin/activate

# Install dependencies with uv
uv pip install -r requirements.txt

# Create .env file
cat > .env << EOF
RELAY_URL=wss://your-app-name.fly.dev/ws/agent
AUTH_TOKEN=your-auth-token-here
EOF
```

### Run the Agent

```bash
# Manual run (foreground)
./run.sh

# You should see:
# [timestamp] Code Remote Agent starting...
# [timestamp] Connecting to relay...
# [timestamp] Connected to relay!
```

### Install as Background Service (launchd)

For persistent operation:

```bash
# Edit the plist file with your username
sed -i '' 's/YOUR_USERNAME/your-mac-username/g' com.code.remote-agent.plist

# Copy to LaunchAgents
cp com.code.remote-agent.plist ~/Library/LaunchAgents/

# Load the service
launchctl load ~/Library/LaunchAgents/com.code.remote-agent.plist

# Check status
launchctl list | grep code.remote
```

**View logs:**
```bash
tail -f /tmp/code-remote-agent.log
```

**Manage the service:**
```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.code.remote-agent.plist

# Start
launchctl load ~/Library/LaunchAgents/com.code.remote-agent.plist
```

## Step 3: Configure Your AI Client

1. Open your MCP-compatible AI client (e.g., Claude.ai)
2. Go to **Settings** > **Connectors** > **MCP**
3. Add a new MCP server:
   - **Name:** Code Remote (or any name you prefer)
   - **URL:** `https://your-app-name.fly.dev/sse`
4. Save and enable the connector

## Step 4: Test the Connection

In your AI client, ask:

> "Check if my Mac agent is connected"

The AI should use the `check_agent_status` tool and confirm the connection.

Try a simple command:

> "What's my Mac's hostname?"

The AI will use `run_shell_command` with `hostname` to show your Mac's name.

## Troubleshooting

### Agent won't connect

1. **Check auth token matches:**
   ```bash
   # On Fly.io
   fly secrets list

   # In agent .env
   cat .env | grep AUTH_TOKEN
   ```

2. **Check network connectivity:**
   ```bash
   curl -I https://your-app-name.fly.dev/health
   ```

3. **Check agent logs:**
   ```bash
   tail -f /tmp/code-remote-agent.log
   ```

### Commands timeout

1. **Increase timeout in command:**
   The AI can specify longer timeouts for slow commands

2. **Check if agent is responding:**
   Look for command receipts in agent logs

### MCP not working in AI client

1. **Verify MCP connector URL** is correct (ends with `/sse`)
2. **Check server health** returns `"status":"ok"`
3. **Ensure agent is connected** (health shows `"agent_connected":true`)

## Next Steps

- [Deployment Guide](DEPLOYMENT.md) - Advanced deployment options
- [Architecture](ARCHITECTURE.md) - Understanding the system design
