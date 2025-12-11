#!/bin/bash

# Start Docker daemon in the background
echo "Starting Docker daemon..."
dockerd --host=unix:///var/run/docker.sock --host=tcp://127.0.0.1:2375 &

# Wait for Docker to be ready
echo "Waiting for Docker to initialize..."
while ! docker info > /dev/null 2>&1; do
    sleep 1
done

echo "Docker is ready!"

# Set Docker environment variables
export DOCKER_HOST=unix:///var/run/docker.sock

# Build the VM image if it doesn't exist
echo "Building VM image..."
if ! docker image inspect telegram-vm-bot:latest > /dev/null 2>&1; then
    docker build -t telegram-vm-bot:latest -f /app/Dockerfile .
fi

echo "Starting Telegram bot..."
cd /app
python3 src/bot.py