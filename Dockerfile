FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install Docker and additional tools needed
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
    docker.io \
    uidmap \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Configure Docker rootless
RUN useradd -rm -d /home/devuser -s /bin/bash -g root -G sudo -u 1000 devuser && \
    echo 'devuser:password' | chpasswd

# Install additional dependencies for Docker rootless
RUN apt-get update && apt-get install -y \
    dbus-user-session \
    fuse-overlayfs \
    slirp4netns \
    && rm -rf /var/lib/apt/lists/*

# Set up Docker rootless for devuser
USER devuser
WORKDIR /home/devuser
RUN mkdir -p ~/.docker && \
    echo '{"experimental": true}' > ~/.docker/config.json
USER root

# Install ttyd (Web Terminal)
RUN wget -O /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    && chmod +x /usr/local/bin/ttyd

# Install Cloudflare Tunnel (cloudflared) - Pre-install during build following official instructions
RUN apt-get update && apt-get install -y curl \
    && mkdir -p --mode=0755 /usr/share/keyrings \
    && curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null \
    && echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main' | tee /etc/apt/sources.list.d/cloudflared.list \
    && apt-get update && apt-get install -y cloudflared \
    && rm -rf /var/lib/apt/lists/*

# Create directory for web terminal tools that can be copied to user containers
RUN mkdir -p /opt/web-terminal-tools \
    && cp /usr/local/bin/ttyd /opt/web-terminal-tools/ \
    && cp /usr/bin/cloudflared /opt/web-terminal-tools/

# Configure SSH
RUN mkdir /var/run/sshd

# Set default password for devuser (will be overridden by the bot)
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
