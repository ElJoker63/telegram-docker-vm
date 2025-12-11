#!/bin/bash

# Set up environment for rootless Docker
export XDG_RUNTIME_DIR=/run/user/1000
export DOCKER_HOST=unix://${XDG_RUNTIME_DIR}/docker.sock

# Start Docker rootless daemon in the background
echo "Starting Docker rootless daemon..."
/usr/bin/dockerd-rootless.sh --experimental --storage-driver=vfs &

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

# Run as devuser (UID 1000) which is the rootless Docker user
exec gosu devuser python3 src/bot.py