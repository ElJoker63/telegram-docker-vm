# Telegram Docker VM Manager

A Telegram bot that orchestrates isolated Docker-based development environments (VMs) with SSH access. It allows users to provision containers on-demand and administrators to manage resources dynamically.

## Features

*   **On-Demand VMs**: Users can create, start, stop, and destroy their own isolated Ubuntu environments.
*   **SSH Access**: Automatically generates credentials and exposes a port for SSH connection.
*   **Dynamic Resource Management**: Admins can configure RAM, CPU, and GPU availability globally without restarting the bot.
*   **GPU Passthrough**: Support for NVIDIA GPUs (requires NVIDIA Container Toolkit).
*   **Persistence**: User states and global configurations are saved in a SQLite database.

## Prerequisites

*   **Windows 11 (Host)** with WSL2 enabled.
*   **Docker Desktop** configured with WSL2 backend.
*   **Python 3.8+**
*   *(Optional)* NVIDIA GPU with drivers installed and NVIDIA Container Toolkit configured for Docker.

## Installation

1.  **Clone the repository** (or extract the project files):
    ```bash
    cd /path/to/project
    ```

2.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables**:
    *   Copy `.env.example` to `.env`:
        ```bash
        cp .env.example .env
        ```
    *   Edit `.env` and fill in your details:
        *   `TELEGRAM_BOT_TOKEN`: Get this from @BotFather on Telegram.
        *   `ADMIN_USER_ID`: Your Telegram User ID (get it from @userinfobot).

4.  **Run the Bot**:
    Make sure you are in the project root directory.
    ```bash
    python src/bot.py
    ```
    *The bot will automatically build the Docker image (`telegram-vm-bot:latest`) and initialize the database on the first run.*

## Usage

### User Commands
*   `/create` - Provision a new VM based on current global settings.
*   `/status` - View VM status, IP, SSH port, and credentials.
*   `/start_vm` - Start a stopped VM.
*   `/stop` - Stop the running VM to save resources.
*   `/destroy` - Permanently delete the VM and data.
*   `/exec [command]` - Execute a shell command inside your VM and see the output (e.g., `/exec ls -la`).
*   `/web_terminal` - Generate a temporary Pinggy.io link to access a full web-based terminal.

### Admin Commands (Admin Only)
*   `/admin_info` - View global config and list of active containers.
*   `/config_gpu [on|off]` - Enable/Disable GPU passthrough for **new** containers.
*   `/config_ram [value]` - Set default RAM limit (e.g., `4g`, `512m`).
*   `/config_cpu [n]` - Set default CPU thread limit.
*   `/force_stop [user_id]` - Forcefully stop a specific user's container.
*   `/maintenance [on|off]` - Toggle maintenance mode. When ON, it stops all running VMs and prevents new ones from being created or started.

## Project Structure

*   `src/bot.py`: Main entry point and Telegram command handlers.
*   `src/config_manager.py`: Database interactions (SQLite).
*   `src/docker_handler.py`: Docker SDK wrapper for container management.
*   `data/`: Stores the SQLite database (`bot_data.db`).
*   `Dockerfile`: Template for the user VMs (Ubuntu + SSH).

## Troubleshooting

*   **GPU Error**: If `/create` fails with GPU enabled, ensure your Docker Desktop supports GPU and the NVIDIA Container Toolkit is installed. You can disable GPU via `/config_gpu off`.
*   **Connection Refused**: Ensure the bot is running and the container status is `UP`.
*   **Docker Connection Error**: If you see `Not supported URL scheme http+docker`, it means you have a dependency conflict. We have updated `requirements.txt` to use the latest Docker SDK which fixes this. **Please run `pip install -r requirements.txt --upgrade` to apply the fix.**