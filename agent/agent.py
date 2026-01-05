#!/usr/bin/env python3
"""
Code Remote Agent

Headless daemon that connects to the relay service and executes commands.
Runs on your machine, auto-executes approved commands from AI assistants.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

# --- Configuration ---

# IMPORTANT: Set RELAY_URL in .env file (see .env.example)
# Format: wss://YOUR-APP-NAME.fly.dev/ws/agent
RELAY_URL = os.getenv("RELAY_URL", "")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
RECONNECT_DELAY = 5  # seconds
MAX_OUTPUT_SIZE = 1_000_000  # 1MB max output
DEFAULT_SHELL = os.getenv("SHELL", "/bin/sh")

# Safety: directories the agent is allowed to access
ALLOWED_PATHS = [
    Path.home(),
    Path("/tmp"),
    Path("/var/tmp"),
]

# --- Logging ---

def log(message: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def log_error(message: str):
    log(f"ERROR: {message}")


# --- Path Safety ---

def is_path_allowed(path_str: str) -> bool:
    """Check if a path is within allowed directories"""
    try:
        path = Path(path_str).expanduser().resolve()
        return any(
            path == allowed or allowed in path.parents
            for allowed in ALLOWED_PATHS
        )
    except Exception:
        return False


# --- Command Execution ---

async def execute_shell(command: str, working_dir: Optional[str], timeout: int) -> dict:
    """Execute a shell command"""
    log(f"Executing: {command}")
    
    cwd = None
    if working_dir:
        cwd = Path(working_dir).expanduser().resolve()
        if not is_path_allowed(str(cwd)):
            return {
                "status": "failed",
                "error": f"Working directory not allowed: {working_dir}",
                "exit_code": 1
            }
    
    try:
        # stdin=DEVNULL prevents commands from hanging waiting for interactive input
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            shell=True,
            executable=DEFAULT_SHELL
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "status": "timeout",
                "error": f"Command timed out after {timeout} seconds",
                "exit_code": -1
            }
        
        output = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace")
        
        # Truncate if too large
        if len(output) > MAX_OUTPUT_SIZE:
            output = output[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
        if len(error) > MAX_OUTPUT_SIZE:
            error = error[:MAX_OUTPUT_SIZE] + "\n... (error truncated)"
        
        return {
            "status": "completed" if process.returncode == 0 else "failed",
            "output": output,
            "error": error if error else None,
            "exit_code": process.returncode
        }
    
    except Exception as e:
        log_error(f"Shell execution error: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "exit_code": 1
        }


async def read_file(path_str: str) -> dict:
    """Read a file's contents"""
    log(f"Reading file: {path_str}")
    
    try:
        path = Path(path_str).expanduser().resolve()
        
        if not is_path_allowed(str(path)):
            return {
                "status": "failed",
                "error": f"Path not allowed: {path_str}",
                "exit_code": 1
            }
        
        if not path.exists():
            return {
                "status": "failed",
                "error": f"File not found: {path_str}",
                "exit_code": 1
            }
        
        if not path.is_file():
            return {
                "status": "failed",
                "error": f"Not a file: {path_str}",
                "exit_code": 1
            }
        
        content = path.read_text(errors="replace")
        
        if len(content) > MAX_OUTPUT_SIZE:
            content = content[:MAX_OUTPUT_SIZE] + "\n... (content truncated)"
        
        return {
            "status": "completed",
            "output": content,
            "exit_code": 0
        }
    
    except Exception as e:
        log_error(f"Read file error: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "exit_code": 1
        }


async def write_file(path_str: str, content: str) -> dict:
    """Write content to a file"""
    log(f"Writing file: {path_str}")
    
    try:
        path = Path(path_str).expanduser().resolve()
        
        if not is_path_allowed(str(path)):
            return {
                "status": "failed",
                "error": f"Path not allowed: {path_str}",
                "exit_code": 1
            }
        
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        path.write_text(content)
        
        return {
            "status": "completed",
            "output": f"Written {len(content)} bytes to {path}",
            "exit_code": 0
        }
    
    except Exception as e:
        log_error(f"Write file error: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "exit_code": 1
        }


async def list_dir(path_str: str) -> dict:
    """List directory contents"""
    log(f"Listing directory: {path_str}")
    
    try:
        path = Path(path_str).expanduser().resolve()
        
        if not is_path_allowed(str(path)):
            return {
                "status": "failed",
                "error": f"Path not allowed: {path_str}",
                "exit_code": 1
            }
        
        if not path.exists():
            return {
                "status": "failed",
                "error": f"Directory not found: {path_str}",
                "exit_code": 1
            }
        
        if not path.is_dir():
            return {
                "status": "failed",
                "error": f"Not a directory: {path_str}",
                "exit_code": 1
            }
        
        entries = []
        for entry in sorted(path.iterdir()):
            entry_type = "dir" if entry.is_dir() else "file"
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except:
                size = 0
            entries.append(f"{entry_type}\t{size}\t{entry.name}")
        
        return {
            "status": "completed",
            "output": "\n".join(entries),
            "exit_code": 0
        }
    
    except Exception as e:
        log_error(f"List dir error: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "exit_code": 1
        }


async def handle_command(data: dict) -> dict:
    """Route command to appropriate handler"""
    command_type = data.get("command_type")
    command_id = data.get("id")
    
    log(f"Received command {command_id}: {command_type}")
    
    if command_type == "shell":
        result = await execute_shell(
            data.get("command", ""),
            data.get("working_dir"),
            data.get("timeout", 60)
        )
    elif command_type == "read_file":
        result = await read_file(data.get("path", ""))
    elif command_type == "write_file":
        result = await write_file(data.get("path", ""), data.get("content", ""))
    elif command_type == "list_dir":
        result = await list_dir(data.get("path", ""))
    else:
        result = {
            "status": "failed",
            "error": f"Unknown command type: {command_type}",
            "exit_code": 1
        }
    
    return {
        "type": "result",
        "id": command_id,
        **result
    }


# --- WebSocket Connection ---

async def connect_and_run():
    """Connect to relay and process commands"""
    url = f"{RELAY_URL}?token={AUTH_TOKEN}"
    
    log(f"Connecting to relay...")
    
    async with websockets.connect(
        url,
        ping_interval=30,
        ping_timeout=10,
        close_timeout=5
    ) as ws:
        log("Connected to relay!")
        
        # Start ping task to keep connection alive
        async def ping_loop():
            while True:
                await asyncio.sleep(25)
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except:
                    break
        
        ping_task = asyncio.create_task(ping_loop())
        
        try:
            async for message in ws:
                data = json.loads(message)
                
                if data.get("type") == "execute":
                    result = await handle_command(data)
                    await ws.send(json.dumps(result))
                elif data.get("type") == "pong":
                    pass  # Ping response, ignore
                else:
                    log(f"Unknown message type: {data.get('type')}")
        
        finally:
            ping_task.cancel()


async def main():
    """Main loop with reconnection"""
    if not RELAY_URL:
        log_error("RELAY_URL environment variable not set!")
        log_error("Set it in .env file: RELAY_URL=wss://YOUR-APP-NAME.fly.dev/ws/agent")
        sys.exit(1)

    if not AUTH_TOKEN:
        log_error("AUTH_TOKEN environment variable not set!")
        sys.exit(1)

    log("Code Remote Agent starting...")
    log(f"Relay URL: {RELAY_URL.split('?')[0]}")
    log(f"Home directory: {Path.home()}")
    
    while True:
        try:
            await connect_and_run()
        except ConnectionClosed as e:
            log(f"Connection closed: {e}")
        except Exception as e:
            log_error(f"Connection error: {e}")
        
        log(f"Reconnecting in {RECONNECT_DELAY} seconds...")
        await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        log("Shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    asyncio.run(main())
