#!/bin/bash
set -e

# Code Remote Agent Setup Script
# Run this on your machine after deploying the server

echo "Code Remote Agent Setup"
echo "======================="
echo ""

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "ERROR: uv is required but not installed."
    echo "       Install via: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Get the directory where this script lives
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create virtual environment with uv
echo "Creating virtual environment..."
uv venv "$SCRIPT_DIR/.venv"

# Install dependencies
echo "Installing dependencies..."
uv pip install -r "$SCRIPT_DIR/requirements.txt"

# Check if .env exists, if not create from example
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "Configuration"
    echo "-------------"

    # Relay URL - must be set to your server
    echo "Enter your server URL (format: wss://YOUR-APP-NAME.fly.dev/ws/agent)"
    read -p "Relay URL: " RELAY_URL
    if [ -z "$RELAY_URL" ]; then
        echo "ERROR: Relay URL is required!"
        exit 1
    fi

    read -p "Auth Token (from server secrets): " AUTH_TOKEN
    if [ -z "$AUTH_TOKEN" ]; then
        echo "ERROR: Auth token is required!"
        exit 1
    fi

    # Create .env file
    cat > "$SCRIPT_DIR/.env" << EOF
RELAY_URL=$RELAY_URL
AUTH_TOKEN=$AUTH_TOKEN
EOF

    echo "Configuration saved to .env"
else
    echo "Using existing .env configuration"
fi

# Make run.sh executable
chmod +x "$SCRIPT_DIR/run.sh"

echo ""
echo "Setup complete!"
echo ""
echo "To run the agent manually:"
echo "  cd $SCRIPT_DIR && ./run.sh"
echo ""
echo "To install as a background service (launchd on macOS):"
echo "  1. Edit com.code.remote-agent.plist with your username"
echo "  2. cp com.code.remote-agent.plist ~/Library/LaunchAgents/"
echo "  3. launchctl load ~/Library/LaunchAgents/com.code.remote-agent.plist"
echo ""
echo "View logs at: /tmp/code-remote-agent.log"
