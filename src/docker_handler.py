import docker
from docker.types import DeviceRequest
import logging
import secrets
import string
import time
import re
import asyncio
import os
from docker.errors import DockerException, NotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Docker Python SDK Version: {docker.__version__}")

def safe_decode(output):
    """Safely decode container output, handling encoding errors."""
    if isinstance(output, bytes):
        try:
            return output.decode('utf-8')
        except UnicodeDecodeError:
            return output.decode('utf-8', errors='ignore')
    return str(output)

try:
    client = docker.from_env()
    client.ping() # Verify connection
    logger.info("Successfully connected to Docker daemon.")
except Exception as e:
    logger.warning(f"Docker not available: {e}")
    logger.warning("Running in limited mode without Docker functionality.")
    client = None

IMAGE_NAME = "ubuntu:22.04"

# Cloudflare configuration - load from environment variables
CLOUDFLARE_TOKEN = os.getenv("CLOUDFLARE_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

def build_image():
    """Build the Docker image if it doesn't exist."""
    if not client:
        return False
    try:
        logger.info(f"Building image {IMAGE_NAME}...")
        client.images.build(path=".", tag=IMAGE_NAME, rm=True)
        logger.info("Image built successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to build image: {e}")
        return False

def generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for i in range(length))

async def create_container(user_id, gpu_enabled, ram_limit, cpu_limit):
    """Create and start a new container with specified resources."""
    if not client:
        raise Exception("Docker client not initialized")

    container_name = f"vm_user_{user_id}"
    password = generate_password()
    
    # Configure Host Config
    host_config_params = {
        "port_bindings": {22: None}, # Bind to random host port
        "mem_limit": ram_limit,
        "nano_cpus": int(cpu_limit * 1e9) # Docker takes nano cpus
    }

    if gpu_enabled:
        # Add GPU support
        host_config_params["device_requests"] = [
            DeviceRequest(count=-1, capabilities=[['gpu']])
        ]

    try:
        # Remove existing container if any (cleanup)
        try:
            old_container = client.containers.get(container_name)
            old_container.remove(force=True)
        except NotFound:
            pass

        container = client.containers.run(
            IMAGE_NAME,
            detach=True,
            name=container_name,
            ports={'22/tcp': None},
            mem_limit=ram_limit,
            nano_cpus=int(cpu_limit * 1e9),
            device_requests=host_config_params.get("device_requests"),
            restart_policy={"Name": "on-failure"},
            environment={
                'DEBIAN_FRONTEND': 'noninteractive',
                'TZ': 'Europe/Madrid'
            },
            command="sleep infinity"  # Keep container running
        )
        
        # Wait for container to be fully running
        container.reload()
        max_attempts = 10
        attempt = 0

        while attempt < max_attempts:
            try:
                # Check if container is running
                container.reload()
                if container.status == 'running':
                    # Set the password inside the container
                    # Use a simple approach that works reliably
                    try:
                        # Try to use openssl if available, otherwise use simple password
                        openssl_cmd = f"openssl passwd -1 '{password}' 2>/dev/null"
                        exit_code, hash_output = container.exec_run(openssl_cmd, user='root')
                        if exit_code == 0:
                            encrypted_pass = hash_output.decode().strip()
                            # Use usermod to set the password hash
                            usermod_cmd = f"usermod -p '{encrypted_pass}' devuser"
                            exit_code2, output2 = container.exec_run(usermod_cmd, user='root')
                            if exit_code2 == 0:
                                logger.info("Password set successfully using openssl + usermod")
                            else:
                                logger.warning(f"usermod failed: {safe_decode(output2)}")
                                raise Exception("usermod failed")
                        else:
                            # Fallback to simple password setting
                            logger.warning("Openssl not available, using simple password method")
                            raise Exception("openssl not available")
                    except Exception as e:
                        # Fallback to simpler method - just set a known password
                        logger.warning(f"Advanced password methods failed ({e}), using simple password")
                        simple_cmd = f"sh -c 'echo \"devuser:{password}\" | chpasswd 2>/dev/null || echo \"Password setting failed but continuing\"'"
                        container.exec_run(simple_cmd, user='root')
                        logger.info("Attempted simple password setting (may or may not work due to PAM restrictions)")
                    break
                else:
                    await asyncio.sleep(1)
                    attempt += 1
            except Exception as e:
                logger.warning(f"Container not ready yet, retrying... ({attempt}/{max_attempts}): {e}")
                await asyncio.sleep(1)
                attempt += 1

        if attempt >= max_attempts:
            logger.error("Container failed to start within the expected time")
            container.remove(force=True)
            raise Exception("Container failed to start")

        # Install web terminal tools (ttyd and cloudflared)
        logger.info("Installing web terminal tools...")
        try:
            # Install tools using apt-get with better error handling and retries
            logger.info("Installing curl and other dependencies...")

            # First update package list with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                exit_code, output = container.exec_run("apt-get update", user='root')
                if exit_code == 0:
                    logger.info("Package list updated successfully")
                    break
                else:
                    logger.warning(f"apt-get update failed (attempt {attempt + 1}/{max_retries}): {output.decode()}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                    else:
                        logger.error("Failed to update package list after multiple attempts")
                        # Try to continue with cached package list

            # Install curl and wget with better dependency handling
            exit_code, output = container.exec_run("apt-get install -y --no-install-recommends curl wget ca-certificates", user='root')
            if exit_code != 0:
                logger.warning(f"curl/wget installation failed: {output.decode()}")
                # Try minimal installation
                exit_code, output = container.exec_run("apt-get install -y --no-install-recommends curl", user='root')
                if exit_code != 0:
                    logger.error("Failed to install curl - web terminal tools will not work")
                    raise Exception("Critical dependency (curl) could not be installed")
            else:
                logger.info("curl and wget installed successfully")

            # Try to install ttyd from Ubuntu repos first
            logger.info("Installing ttyd...")
            exit_code, output = container.exec_run("apt-get install -y ttyd", user='root')
            if exit_code != 0:
                logger.info("ttyd not in repos, downloading binary...")
                # Fallback to binary download
                exit_code, output = container.exec_run(
                    "curl -L https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -o /usr/local/bin/ttyd && chmod +x /usr/local/bin/ttyd",
                    user='root'
                )
                if exit_code == 0:
                    logger.info("ttyd binary installed successfully")
                else:
                    logger.warning(f"ttyd binary installation failed: {output.decode()}")
            else:
                logger.info("ttyd installed from repository")

            # Install cloudflared directly via apt (repository is pre-configured in image)
            logger.info("Installing cloudflared...")
            cloudflared_installed = False
            try:
                # Execute commands separately to avoid shell interpretation issues
                commands = [
                    ("apt-get update", "Updating package lists"),
                    ("apt-get install -y cloudflared", "Installing cloudflared")
                ]

                for cmd, description in commands:
                    logger.info(f"{description}...")
                    exit_code, output = container.exec_run(cmd, user='root')
                    if exit_code != 0:
                        logger.warning(f"{description} failed: {safe_decode(output)}")
                        break
                else:
                    logger.info("cloudflared installed successfully via apt")
                    cloudflared_installed = True

                if not cloudflared_installed:
                    logger.warning("apt installation failed, trying direct download...")
                    # Try direct download as fallback
                    wget_cmd = "sh -c 'wget -q -O /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /usr/local/bin/cloudflared'"
                    exit_code, output = container.exec_run(wget_cmd, user='root')
                    if exit_code == 0:
                        logger.info("cloudflared installed successfully via direct download")
                        cloudflared_installed = True
                    else:
                        logger.warning(f"Direct download failed: {safe_decode(output)}")

                if not cloudflared_installed:
                    # Create dummy script as last resort
                    container.exec_run(
                        'mkdir -p /usr/local/bin && echo "#!/bin/bash\necho \"Web terminal not available: cloudflared could not be installed\"\nexit 1" > /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared',
                        user='root'
                    )
                    logger.warning("Created dummy cloudflared script")

            except Exception as e:
                logger.warning(f"Cloudflared installation failed: {str(e)}")
                # Create dummy script
                container.exec_run(
                    'mkdir -p /usr/local/bin && echo "#!/bin/bash\necho \"Web terminal not available: cloudflared could not be installed\"\nexit 1" > /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared',
                    user='root'
                )

            # Verify installations
            exit_code, output = container.exec_run("which ttyd", user='root')
            if exit_code == 0:
                logger.info("ttyd verification successful")
            else:
                logger.warning("ttyd verification failed")

            exit_code, output = container.exec_run("which cloudflared", user='root')
            if exit_code == 0:
                logger.info("cloudflared verification successful")
            else:
                logger.warning("cloudflared verification failed")

            logger.info("Web terminal tools installation completed")
        except Exception as e:
            logger.warning(f"Failed to install web terminal tools: {str(e)}")
            # Continue anyway - web terminal won't work but SSH will

        # Get assigned port
        container.reload()
        ssh_port = container.ports['22/tcp'][0]['HostPort']
        
        return {
            "container_id": container.id,
            "container_name": container_name,
            "ssh_port": ssh_port,
            "password": password
        }

    except Exception as e:
        logger.error(f"Failed to create container: {e}")
        raise e

def stop_container(container_id):
    """Stop a running container."""
    if not client: return False
    try:
        container = client.containers.get(container_id)
        container.stop()
        return True
    except Exception as e:
        logger.error(f"Error stopping container: {e}")
        return False

def start_container(container_id):
    """Start a stopped container."""
    if not client: return False
    try:
        container = client.containers.get(container_id)
        container.start()
        return True
    except Exception as e:
        logger.error(f"Error starting container: {e}")
        return False

def remove_container(container_id):
    """Remove a container and its volumes."""
    if not client: return False
    try:
        container = client.containers.get(container_id)
        container.remove(force=True)
        return True
    except Exception as e:
        logger.error(f"Error removing container: {e}")
        return False

def get_container_status(container_id):
    """Get current status of a container."""
    if not client: return "UNKNOWN"
    try:
        container = client.containers.get(container_id)
        return container.status.upper() # running, exited, etc.
    except NotFound:
        return "DESTROYED"
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return "ERROR"

def exec_command(container_id, command):
    """Execute a command inside the container and return the output."""
    if not client: return "Docker client not initialized"
    try:
        container = client.containers.get(container_id)
        # Run as root (devuser may not exist in basic containers)
        exit_code, output = container.exec_run(f"bash -c '{command}'", user='root')
        return output.decode('utf-8')
    except Exception as e:
        logger.error(f"Exec error: {e}")
        return f"Error: {str(e)}"

async def start_web_ssh_tunnel(container_id):
    """Start ttyd and Cloudflare Tunnel, returning the HTTPS URL."""
    if not client: return "Docker client not initialized"
    try:
        container = client.containers.get(container_id)

        # Check if required tools are installed
        exit_code, _ = container.exec_run("which ttyd", user='root')
        if exit_code != 0:
            return "Web terminal not available: ttyd not installed in container"

        exit_code, _ = container.exec_run("which cloudflared", user='root')
        if exit_code != 0:
            return "Web terminal not available: cloudflared not installed in container"

        # 1. Start ttyd (if not already running)
        exit_code, _ = container.exec_run("pgrep ttyd", user='root')
        if exit_code != 0:
            # Run ttyd on port 7681 without origin checking for tunnel usage
            cmd = "nohup ttyd -p 7681 --writable bash > /tmp/ttyd.log 2>&1 &"
            container.exec_run(f"sh -c '{cmd}'", detach=True, user='root')
            logger.info("Started ttyd on port 7681")

        # 2. Start Cloudflare Tunnel
        # Kill existing tunnel if any
        container.exec_run("pkill -f cloudflared", user='root')
        await asyncio.sleep(1)  # Wait for process to terminate

        # Start new tunnel pointing to ttyd (http://localhost:7681)
        # Use unauthenticated quick tunnel for simplicity and reliability
        cmd = "nohup cloudflared tunnel --url http://localhost:7681 > /tmp/cloudflared.log 2>&1 &"
        logger.info("Starting Cloudflare quick tunnel")

        container.exec_run(f"sh -c '{cmd}'", detach=True, user='root')
        logger.info("Started Cloudflare tunnel")

        # Wait for URL - increased timeout and better error handling
        log = ""
        max_attempts = 60  # 60 seconds timeout for better reliability
        for i in range(max_attempts):
            await asyncio.sleep(1)
            try:
                exit_code, output = container.exec_run("cat /tmp/cloudflared.log 2>/dev/null || echo 'no log yet'", user='root')
                log = output.decode('utf-8')

                # Updated regex to handle different Cloudflare tunnel URL formats
                match = re.search(r'(https://[\w.-]+\.(trycloudflare\.com|cfargotunnel\.com|cloudflare\.com))', log)
                if not match:
                    # Try alternative URL patterns for authenticated tunnels
                    match = re.search(r'(https://[^\s]+\.cloudflare\.com)', log)
                if not match:
                    # Last resort - any https URL
                    match = re.search(r'(https://[^\s]+)', log)

                if match:
                    url = match.group(1)
                    # Validate the URL format
                    if url.startswith('https://') and 'cloudflare' in url.lower():
                        logger.info(f"Cloudflare tunnel URL obtained: {url}")
                        return url
                    else:
                        logger.warning(f"Invalid Cloudflare URL format detected: {url}")

                # Check for errors in the log
                if "failed" in log.lower() or "error" in log.lower():
                    logger.warning(f"Cloudflared error detected: {log}")

                # Check if cloudflared process is still running
                exit_code, _ = container.exec_run("pgrep -f cloudflared", user='root')
                if exit_code != 0:
                    logger.error("Cloudflared process has terminated unexpectedly")
                    break

            except Exception as e:
                logger.warning(f"Error reading cloudflared log: {e}")
                continue

        # If failed, return detailed error information with troubleshooting suggestions
        logger.error(f"Failed to get Cloudflare URL after {max_attempts} seconds")
        error_msg = f"Failed to establish web terminal tunnel. Last log output: {log[-500:] if log else 'No log output'}"

        # Check for common issues
        if "permission denied" in log.lower():
            error_msg += "\n\n🔧 Troubleshooting: The container may not have permission to create network tunnels."
        elif "network" in log.lower() or "connection" in log.lower():
            error_msg += "\n\n🔧 Troubleshooting: The container may not have proper internet access."
        elif "authentication" in log.lower() or "token" in log.lower():
            error_msg += "\n\n🔧 Troubleshooting: Cloudflare tunnel may require authentication."

        return error_msg

    except Exception as e:
        logger.error(f"Web SSH tunnel error: {e}")
        return f"Error establishing web terminal: {str(e)}"

def get_container_stats(container_id):
    """Get real-time stats (RAM, CPU) for a container."""
    if not client: return None
    try:
        container = client.containers.get(container_id)
        stats = container.stats(stream=False)
        
        # Calculate CPU usage
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
        system_cpu_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
        number_cpus = stats['cpu_stats']['online_cpus']
        cpu_usage = (cpu_delta / system_cpu_delta) * number_cpus * 100.0 if system_cpu_delta > 0 else 0.0
        
        # Calculate Memory usage
        memory_usage = stats['memory_stats']['usage']
        memory_limit = stats['memory_stats']['limit']
        memory_percent = (memory_usage / memory_limit) * 100.0
        
        # Format output
        return {
            "cpu_percent": round(cpu_usage, 2),
            "memory_usage": f"{round(memory_usage / (1024 * 1024), 2)} MB",
            "memory_limit": f"{round(memory_limit / (1024 * 1024), 2)} MB",
            "memory_percent": round(memory_percent, 2)
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return None