# Code Remote - Deployment Guide

Detailed instructions for deploying and managing the Code Remote server on Fly.io.

## Initial Deployment

### Prerequisites

```bash
# Install Fly.io CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login
```

### Deploy from Scratch

```bash
cd server

# First, edit fly.toml and set your app name:
# app = "YOUR-APP-NAME"

# Create app with volume (use same name as in fly.toml)
fly launch --name YOUR-APP-NAME --region dfw --no-deploy
fly volumes create code_remote_data --size 1 --region dfw

# Generate and set auth token
AUTH_TOKEN=$(openssl rand -hex 32)
echo "Save this token: $AUTH_TOKEN"
fly secrets set AUTH_TOKEN=$AUTH_TOKEN

# Deploy
fly deploy
```

## Managing Secrets

### View Secrets

```bash
fly secrets list
```

### Update Auth Token

```bash
# Generate new token
NEW_TOKEN=$(openssl rand -hex 32)
echo "New token: $NEW_TOKEN"

# Update on server
fly secrets set AUTH_TOKEN=$NEW_TOKEN

# Update agent .env file with new token
```

**Note:** Changing the auth token will disconnect the agent until updated.

## Updating Deployments

### Code Changes

```bash
cd server
fly deploy
```

### View Deployment Status

```bash
fly status
```

### View Recent Deployments

```bash
fly releases
```

### Rollback to Previous Version

```bash
fly releases rollback
```

## Monitoring

### Live Logs

```bash
# All logs
fly logs

# Follow in real-time
fly logs -f
```

### Health Check

```bash
curl https://YOUR-APP-NAME.fly.dev/health
```

Response:
```json
{
  "status": "ok",
  "agent_connected": true,
  "timestamp": "2024-12-22T12:00:00Z"
}
```

### View Command History

```bash
# Requires auth token
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://YOUR-APP-NAME.fly.dev/commands?limit=10"
```

## Scaling

### View Current Configuration

```bash
fly scale show
```

### Adjust Memory/CPU

```bash
# Increase memory
fly scale memory 1024

# Change VM size
fly scale vm shared-cpu-2x
```

### Multiple Regions

```bash
# Add a region
fly regions add ord

# Scale to multiple machines
fly scale count 2
```

## Volume Management

### View Volumes

```bash
fly volumes list
```

### Extend Volume

```bash
fly volumes extend vol_xxxxx -s 2
```

### SSH and Inspect Data

```bash
fly ssh console

# Inside container
sqlite3 /data/code_remote.db
.tables
SELECT COUNT(*) FROM commands;
.quit
```

## Teardown

### Stop the App

```bash
fly scale count 0
```

### Delete Everything

```bash
# Delete the app (includes volumes)
fly apps destroy YOUR-APP-NAME

# Or keep the app but delete volumes
fly volumes destroy vol_xxxxx
```

## Cost Management

### Current App (Shared CPU, 512MB)

- ~$2-5/month for always-on single machine
- Volume storage: $0.15/GB/month

### Reduce Costs

Edit `fly.toml` to allow auto-stopping:

```toml
[http_service]
  auto_stop_machines = 'suspend'  # Instead of 'off'
```

**Note:** This adds latency when waking from suspend.

## Troubleshooting

### App Not Starting

```bash
# Check logs
fly logs

# Check machine status
fly machine list
fly machine status <machine-id>
```

### Database Issues

```bash
# SSH into container
fly ssh console

# Check database
ls -la /data/
sqlite3 /data/code_remote.db ".schema"
```

### WebSocket Connection Drops

1. Check the agent is running: `ps aux | grep agent.py`
2. Check network: `curl -I https://YOUR-APP-NAME.fly.dev/health`
3. Review agent logs: `tail -f /tmp/code-remote-agent.log`

## Configuration Reference

### fly.toml

```toml
app = "YOUR-APP-NAME"  # <-- Change this to your unique app name
primary_region = 'dfw'

[build]
# Uses Dockerfile in same directory

[env]
DATABASE_PATH = '/data/code_remote.db'
PORT = '8080'

[[mounts]]
source = 'code_remote_data'
destination = '/data'

[http_service]
internal_port = 8080
force_https = true
auto_stop_machines = 'off'    # Keep running for WebSocket
auto_start_machines = true
min_machines_running = 1

[[vm]]
size = 'shared-cpu-1x'
memory = '512mb'
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_TOKEN` | Authentication token (set via secrets) | Required |
| `DATABASE_PATH` | SQLite database path | `/data/code_remote.db` |
| `PORT` | HTTP server port | `8080` |
