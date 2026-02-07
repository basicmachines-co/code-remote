FROM python:3.11-slim

WORKDIR /app

# Install Tailscale
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://tailscale.com/install.sh | sh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create directories for Tailscale state
RUN mkdir -p /data/tailscale /var/run/tailscale

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
