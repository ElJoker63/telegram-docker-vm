# Telegram Docker VM Manager

A Telegram bot that orchestrates isolated Docker-based development environments (VMs) with secure SSH and web terminal access. It allows users to provision containers on-demand and administrators to manage resources dynamically, without exposing any ports externally.

## Features

*   **On-Demand VMs**: Users can create, start, stop, and destroy their own isolated Ubuntu environments.
*   **Multiple VM Plans**: Choose from different resource configurations (Basic, Standard, Pro, Enterprise).
*   **SSH Access**: Automatically generates credentials and exposes a port for SSH connection.
*   **Dynamic Resource Management**: Admins can configure RAM, CPU, and GPU availability globally without restarting the bot.
*   **GPU Passthrough**: Support for NVIDIA GPUs (requires NVIDIA Container Toolkit).
*   **User Authorization**: Admin-controlled whitelist system to restrict bot access to approved users only.
*   **Command Registration**: Bot automatically registers all available commands with Telegram for better user experience.
*   **Asynchronous Operations**: All Docker operations are fully asynchronous to prevent blocking other users.
*   **Secure Web Terminal**: Cloudflare Tunnel provides HTTPS access without exposing any ports externally.
*   **Persistence**: User states and global configurations are saved in a SQLite database.

## Prerequisites

*   **Windows 11 (Host)** with WSL2 enabled.
*   **Docker Desktop** configured with WSL2 backend.
*   **Python 3.8+**
*   **Internet connection** (for Cloudflare Tunnel - works without public IP)
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
        *   `CLOUDFLARE_TOKEN` (Optional but recommended): Cloudflare API token for reliable web terminals.
        *   `CLOUDFLARE_ACCOUNT_ID` (Optional): Your Cloudflare account ID.

### Cloudflare Setup (Recommended for Web Terminals)

For best web terminal reliability, set up Cloudflare authentication:

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
2. Create a new API token with "Cloudflare Tunnel" permissions
3. Get your Account ID from the Cloudflare dashboard (found in the right sidebar)
4. Add these to your `.env` file:

```env
CLOUDFLARE_TOKEN=your_api_token_here
CLOUDFLARE_ACCOUNT_ID=your_account_id_here
```

**Note**: Web terminals will work without Cloudflare authentication, but authenticated tunnels are more reliable and have fewer limitations.

4.  **Set Up User Authorization** (Optional but Recommended):
    *   By default, only the admin user can access the bot.
    *   To allow other users, use the admin commands:
        *   `/allow_user [user_id] [username]` - Add users to the whitelist.
        *   `/list_allowed` - View currently allowed users.
    *   Users not in the whitelist will receive an access denied message when trying to use any bot commands.

5.  **Run the Bot**:
    Make sure you are in the project root directory.
    ```bash
    python src/bot.py
    ```
    *The bot will automatically build the Docker image (`telegram-vm-bot:latest` for the bot), initialize the database, and register all commands with Telegram on the first run.*

## Usage

### User Commands
*   `/plans` - View available VM plans with different resource configurations.
*   `/create` - Provision a new VM with your assigned plan.
*   `/status` - View VM status, plan details, SSH port, and credentials.
*   `/start_vm` - Start a stopped VM.
*   `/stop` - Stop the running VM to save resources.
*   `/destroy` - Permanently delete the VM and data.
*   `/exec [command]` - Execute a shell command inside your VM and see the output (e.g., `/exec ls -la`).
*   `/web_terminal` - Generate a secure Cloudflare Tunnel link to access a full web-based terminal (no ports exposed).

### Admin Commands (Admin Only)
*   `/admin_info` - View global config and list of active containers.
*   `/config_gpu [on|off]` - Enable/Disable GPU passthrough for **new** containers.
*   `/config_ram [value]` - Set default RAM limit (e.g., `4g`, `512m`).
*   `/config_cpu [n]` - Set default CPU thread limit.
*   `/force_stop [user_id]` - Forcefully stop a specific user's container.
*   `/maintenance [on|off]` - Toggle maintenance mode. When ON, it stops all running VMs and prevents new ones from being created or started.
*   `/allow_user [user_id] [plan_id] [username]` - Add a user to the allowed users list with a specific plan (username is optional).
*   `/remove_user [user_id]` - Remove a user from the allowed users list.
*   `/list_allowed` - List all users who are allowed to use the bot.

## Project Structure

*   `src/bot.py`: Main entry point and Telegram command handlers.
*   `src/config_manager.py`: Database interactions (SQLite).
*   `src/docker_handler.py`: Docker SDK wrapper for container management.
*   `data/`: Stores the SQLite database (`bot_data.db`).
*   `Dockerfile`: Template for the bot container with Docker-in-Docker support.

## Troubleshooting

*   **GPU Error**: If `/create` fails with GPU enabled, ensure your Docker Desktop supports GPU and the NVIDIA Container Toolkit is installed. You can disable GPU via `/config_gpu off`.
*   **Connection Refused**: Ensure the bot is running and the container status is `UP`.
*   **Web Terminal Not Working**: The web terminal uses Cloudflare Tunnel to provide secure access without exposing ports. If it fails:
  * Check that the container has internet access
  * Verify `ttyd` and `cloudflared` are installed (`/web_terminal` will show installation status)
  * The tunnel may take up to 60 seconds to establish
  * If using Cloudflare authentication, ensure your `CLOUDFLARE_TOKEN` is valid
  * Check container logs for specific error messages
  * Try restarting the tunnel with `/web_terminal` command
*   **Docker Connection Error**: If you see `Not supported URL scheme http+docker`, it means you have a dependency conflict. We have updated `requirements.txt` to use the latest Docker SDK which fixes this. **Please run `pip install -r requirements.txt --upgrade` to apply the fix.**
*   **Image Build Issues**: If you encounter issues with the VM image, try rebuilding it manually: `docker build -f Dockerfile.vm -t telegram-vm-user:latest .`