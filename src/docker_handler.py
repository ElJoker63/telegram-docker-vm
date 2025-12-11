import docker
from docker.types import DeviceRequest
import logging
import secrets
import string
import time
import re
from docker.errors import DockerException, NotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Docker Python SDK Version: {docker.__version__}")

try:
    client = docker.from_env()
    client.ping() # Verify connection
    logger.info("Successfully connected to Docker daemon.")
except Exception as e:
    logger.warning(f"Docker not available: {e}")
    logger.warning("Running in limited mode without Docker functionality.")
    client = None

IMAGE_NAME = "ubuntu:22.04"

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

def create_container(user_id, gpu_enabled, ram_limit, cpu_limit):
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
                    exit_code, output = container.exec_run(f"sh -c 'echo devuser:{password} | chpasswd'", user='root')
                    if exit_code != 0:
                        logger.error(f"Failed to set password: {output}")
                    break
                else:
                    time.sleep(1)
                    attempt += 1
            except Exception as e:
                logger.warning(f"Container not ready yet, retrying... ({attempt}/{max_attempts}): {e}")
                time.sleep(1)
                attempt += 1

        if attempt >= max_attempts:
            logger.error("Container failed to start within the expected time")
            container.remove(force=True)
            raise Exception("Container failed to start")

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

def start_web_ssh_tunnel(container_id):
    """Start ttyd and Cloudflare Tunnel, returning the HTTPS URL."""
    if not client: return "Docker client not initialized"
    try:
        container = client.containers.get(container_id)
        
        # 1. Start ttyd (if not already running)
        # -W: Check origin (security), but for quick tunnel we might need to relax it or set it correctly.
        # For simplicity in this demo, we'll allow all origins or just run it.
        exit_code, _ = container.exec_run("pgrep ttyd", user='root')
        if exit_code != 0:
             # Run ttyd on port 7681
             # Using sh -c to handle redirection and backgrounding
             cmd = "nohup ttyd -p 7681 -W bash > /tmp/ttyd.log 2>&1 &"
             container.exec_run(f"sh -c '{cmd}'", detach=True, user='root')
        
        # 2. Start Cloudflare Tunnel
        # Kill existing tunnel if any
        container.exec_run("pkill -f cloudflared", user='root')

        # Start new tunnel pointing to ttyd (http://localhost:7681)
        cmd = "nohup cloudflared tunnel --url http://localhost:7681 > /tmp/cloudflared.log 2>&1 &"
        container.exec_run(f"sh -c '{cmd}'", detach=True, user='root')
        
        # Wait for URL
        # Increased wait time to 30 seconds to allow cloudflared to register
        log = ""
        for i in range(30):
            time.sleep(1)
            exit_code, output = container.exec_run("cat /tmp/cloudflared.log", user='root')
            log = output.decode('utf-8')
            
            # Regex to find the URL: https://random-name.trycloudflare.com
            match = re.search(r'(https://[\w.-]+\.trycloudflare\.com)', log)
            
            if match:
                return match.group(1)
        
        # If failed, return the last few lines of the log for debugging
        return f"Failed to retrieve Cloudflare URL. Log: {log[-1000:] if log else 'No log output'}"
        
    except Exception as e:
        logger.error(f"Web SSH tunnel error: {e}")
        return f"Error: {str(e)}"

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