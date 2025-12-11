#!/bin/bash

# Set up environment for rootless Docker
export XDG_RUNTIME_DIR=/run/user/1000
export DOCKER_HOST=unix://${XDG_RUNTIME_DIR}/docker.sock
export PATH=$PATH:/usr/bin

# Create runtime directory if it doesn't exist
mkdir -p ${XDG_RUNTIME_DIR}
chown devuser ${XDG_RUNTIME_DIR}

# Start Docker rootless daemon with minimal configuration for Coolify
echo "Starting Docker rootless daemon..."
/usr/bin/dockerd --experimental --storage-driver=vfs --userland-proxy=false --iptables=false --ip-masq=false --bridge=none --ipv6=false &

# Wait for Docker to be ready
echo "Waiting for Docker to initialize..."
while ! docker info > /dev/null 2>&1; do
    sleep 1
done

echo "Docker is ready!"

# Build the VM image if it doesn't exist
echo "Building VM image..."
if ! docker image inspect telegram-vm-bot:latest > /dev/null 2>&1; then
    docker build -t telegram-vm-bot:latest -f /app/Dockerfile .
fi

echo "Starting Telegram bot..."
cd /app

# Set proper environment variables for the bot
export TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN .env | cut -d '=' -f2)
export ADMIN_USER_ID=$(grep ADMIN_USER_ID .env | cut -d '=' -f2)
export PYTHONUNBUFFERED=1

# Debug: Show environment variables
echo "TELEGRAM_BOT_TOKEN set to: $TELEGRAM_BOT_TOKEN"
echo "ADMIN_USER_ID set to: $ADMIN_USER_ID"

# Run as devuser (UID 1000) which is the rootless Docker user
exec gosu devuser python3 src/bot.py