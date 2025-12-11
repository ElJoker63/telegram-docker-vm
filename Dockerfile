FROM docker:24.0.7-dind-rootless

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install additional tools needed (rootless Docker already includes docker)
RUN apt-get update && apt-get install -y \
    openssh-server \
    sudo \
    nano \
    iputils-ping \
    curl \
    wget \
    git \
    build-essential \
    cmake \
    libjson-c-dev \
    libwebsockets-dev \
    ffmpeg \
    python3-full \
    python3-pip \
    python3-venv \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd (Web Terminal)
RUN wget -O /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    && chmod +x /usr/local/bin/ttyd

# Install Cloudflare Tunnel (cloudflared)
RUN wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
    && dpkg -i cloudflared-linux-amd64.deb \
    && rm cloudflared-linux-amd64.deb

# Configure SSH
RUN mkdir /var/run/sshd

# Create a user 'devuser' with sudo privileges
RUN useradd -rm -d /home/devuser -s /bin/bash -g root -G sudo -u 1000 devuser 

# Set default password (will be overridden by the bot)
RUN echo 'devuser:password' | chpasswd

EXPOSE 22

# Set working directory
WORKDIR /app

# Copy all project files
COPY . /app

# Install Python dependencies
RUN pip3 install -r requirements.txt

# Create data directory for database
RUN mkdir -p /app/data

# Configure Docker to start automatically
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Correct CMD to run both Docker and the bot
USER root
CMD ["docker-entrypoint.sh"]
