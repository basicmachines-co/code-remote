#!/bin/bash
set -e

# Start Tailscale daemon
tailscaled --state=/data/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &

# Wait for tailscaled to be ready
sleep 2

# Authenticate with Tailscale (uses auth key from environment)
if [ -n "$TAILSCALE_AUTHKEY" ]; then
    tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="code-remote-server"
else
    echo "Warning: TAILSCALE_AUTHKEY not set, Tailscale not configured"
fi

# Start the Python server
exec python server.py
