import os
import logging
import asyncio
import urllib.request
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from functools import wraps

import config_manager as db
import docker_handler as docker

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_USER_ID", 0))

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Decorators ---
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ Access denied. Admin only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- User Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the Docker VM Manager!\n\n"
        "Commands:\n"
        "/create - Create a new VM\n"
        "/status - Check VM status\n"
        "/start_vm - Start your VM\n"
        "/stop - Stop your VM\n"
        "/destroy - Delete your VM\n"
        "/exec [cmd] - Run command in VM\n"
        "/web_terminal - Get Web Terminal Link\n"
    )

async def create_vm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check maintenance mode
    settings = await db.get_settings()
    if not settings:
        await update.message.reply_text("❌ System error: Settings not found.")
        return

    if settings['maintenance_mode'] and user_id != ADMIN_ID:
        await update.message.reply_text("🚧 **System is in Maintenance Mode.**\nCreation of new VMs is currently disabled.")
        return

    # Check if user already has a container
    existing = await db.get_user_container(user_id)
    if existing:
        await update.message.reply_text(f"⚠️ You already have a VM (ID: {existing['container_id']}). Use /destroy first if you want a new one.")
        return

    await update.message.reply_text("⏳ Provisioning your VM... This may take a moment.")

    try:
        # Create container (run in background thread to avoid blocking)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: docker.create_container(
                user_id=user_id,
                gpu_enabled=settings['gpu_enabled'],
                ram_limit=settings['default_ram'],
                cpu_limit=settings['default_cpu']
            )
        )

        # Register in DB
        await db.register_container(
            user_id=user_id,
            container_id=result['container_id'],
            container_name=result['container_name'],
            ssh_port=result['ssh_port']
        )

        # Start Web SSH Tunnel
        await update.message.reply_text("⏳ Establishing secure Web SSH tunnel...")
        web_ssh_url = await loop.run_in_executor(None, docker.start_web_ssh_tunnel, result['container_id'])
        
        msg = (
            "✅ **VM Created Successfully!**\n\n"
            f"🆔 Container ID: `{result['container_id'][:12]}`\n"
            f"👤 User: `devuser`\n"
            f"🔑 Password: `{result['password']}`\n"
            f"🖥️ Resources: {settings['default_ram']} RAM, {settings['default_cpu']} CPU, GPU: {'ON' if settings['gpu_enabled'] else 'OFF'}\n\n"
            "**🖥️ Access Web Terminal:**\n"
            f"[Click here to open terminal]({web_ssh_url})"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Create VM failed: {e}")
        error_msg = str(e)
        if "unshare: operation not permitted" in error_msg:
            await update.message.reply_text(
                "❌ **Docker Container Creation Failed**\n\n"
                "This bot is running in a restricted Docker environment that cannot create nested containers. "
                "The rootless Docker setup inside the container has limitations that prevent VM creation.\n\n"
                "This is a known limitation when running Docker-in-Docker (DinD) with rootless containers. "
                "The bot can manage existing containers but cannot create new ones in this configuration."
            )
        elif "No such image" in error_msg or "pull access denied" in error_msg:
            await update.message.reply_text(
                "❌ **Docker Image Not Available**\n\n"
                "The bot cannot create VMs because the required Docker images are not available in this environment. "
                "This is a limitation of the rootless Docker setup inside the container - it cannot pull images from Docker Hub.\n\n"
                "To use this bot for creating VMs, you would need to:\n"
                "1. Run it outside of a container, or\n"
                "2. Pre-load the required Docker images into the container\n\n"
                "The bot can still manage existing containers if they were created externally."
            )
        else:
            await update.message.reply_text(f"❌ Failed to create VM: {str(e)}")

async def status_vm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    container_data = await db.get_user_container(user_id)
    
    if not container_data:
        await update.message.reply_text("❌ You don't have a VM. Use /create to get one.")
        return

    loop = asyncio.get_running_loop()
    status = await loop.run_in_executor(None, docker.get_container_status, container_data['container_id'])
    
    # Update DB status if changed (optional, but good for consistency)
    if status != container_data['status']:
        await db.update_container_status(user_id, status)

    stats_msg = ""
    if status == "RUNNING":
        stats = await loop.run_in_executor(None, docker.get_container_stats, container_data['container_id'])
        if stats:
            stats_msg = (
                f"\n\n📈 **Resource Usage**\n"
                f"CPU: {stats['cpu_percent']}%\n"
                f"RAM: {stats['memory_usage']} / {stats['memory_limit']} ({stats['memory_percent']}%)\n"
            )

    await update.message.reply_text(
        f"📊 **VM Status**\n"
        f"Status: {status}\n"
        f"SSH Port: {container_data['ssh_port']}\n"
        f"Container ID: {container_data['container_id'][:12]}"
        f"{stats_msg}"
    , parse_mode='Markdown')

async def stop_vm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    container_data = await db.get_user_container(user_id)
    
    if not container_data:
        await update.message.reply_text("❌ No VM found.")
        return

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, docker.stop_container, container_data['container_id'])

    if success:
        await db.update_container_status(user_id, "EXITED")
        await update.message.reply_text("🛑 VM stopped.")
    else:
        await update.message.reply_text("❌ Failed to stop VM.")

async def start_vm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check maintenance mode
    settings = await db.get_settings()
    if settings and settings['maintenance_mode'] and user_id != ADMIN_ID:
        await update.message.reply_text("🚧 **System is in Maintenance Mode.**\nStarting VMs is currently disabled.")
        return

    container_data = await db.get_user_container(user_id)
    
    if not container_data:
        await update.message.reply_text("❌ No VM found.")
        return

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, docker.start_container, container_data['container_id'])

    if success:
        await db.update_container_status(user_id, "RUNNING")
        await update.message.reply_text("▶️ VM started. Re-establishing Web SSH tunnel...")
        
        # Restart Web SSH Tunnel
        web_ssh_url = await loop.run_in_executor(None, docker.start_web_ssh_tunnel, container_data['container_id'])
        
        if "http" in web_ssh_url:
            await update.message.reply_text(f"🖥️ **Web Terminal Ready!**\n\n[Click here to open terminal]({web_ssh_url})", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Failed to restart tunnel: {web_ssh_url}")
    else:
        await update.message.reply_text("❌ Failed to start VM.")

async def destroy_vm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    container_data = await db.get_user_container(user_id)
    
    if not container_data:
        await update.message.reply_text("❌ No VM found.")
        return

    await update.message.reply_text("🗑️ Destroying VM...")
    
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, docker.remove_container, container_data['container_id'])

    if success:
        await db.delete_container(user_id)
        await update.message.reply_text("✅ VM destroyed and data removed.")
    else:
        await update.message.reply_text("❌ Failed to destroy VM (it might already be gone). Removing from DB.")
        await db.delete_container(user_id)

async def exec_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /exec [command]")
        return

    container_data = await db.get_user_container(user_id)
    if not container_data:
        await update.message.reply_text("❌ No VM found.")
        return

    command = " ".join(context.args)
    await update.message.reply_text(f"⏳ Executing: `{command}`...", parse_mode='Markdown')

    loop = asyncio.get_running_loop()
    output = await loop.run_in_executor(None, docker.exec_command, container_data['container_id'], command)
    
    if len(output) > 4000:
        output = output[:4000] + "\n... (truncated)"

    await update.message.reply_text(f"```\n{output}\n```", parse_mode='Markdown')

async def web_terminal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    container_data = await db.get_user_container(user_id)
    
    if not container_data:
        await update.message.reply_text("❌ No VM found.")
        return

    await update.message.reply_text("⏳ Retrieving Web SSH link...")

    loop = asyncio.get_running_loop()
    url = await loop.run_in_executor(None, docker.start_web_ssh_tunnel, container_data['container_id'])
    
    if "http" in url:
        await update.message.reply_text(f"🖥️ **Web Terminal Ready!**\n\n[Click here to open terminal]({url})", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ Failed: {url}")

# --- Admin Commands ---

@admin_only
async def admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = await db.get_settings()
    if not settings:
        await update.message.reply_text("❌ System error: Settings not found.")
        return

    containers = await db.get_all_containers()
    
    msg = (
        "🛠️ **System Configuration**\n"
        f"GPU Enabled: {'✅' if settings['gpu_enabled'] else '❌'}\n"
        f"Default RAM: {settings['default_ram']}\n"
        f"Default CPU: {settings['default_cpu']}\n"
        f"Maintenance Mode: {'✅ ON' if settings['maintenance_mode'] else '❌ OFF'}\n\n"
        f"👥 **Active Users**: {len(containers)}\n"
    )
    
    for c in containers:
        msg += f"- User {c['user_id']}: {c['status']} (Port {c['ssh_port']})\n"
        
    await update.message.reply_text(msg, parse_mode='Markdown')

@admin_only
async def config_gpu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /config_gpu [on|off]")
        return
    
    state = context.args[0].lower()
    if state not in ['on', 'off']:
        await update.message.reply_text("Invalid value. Use 'on' or 'off'.")
        return
    
    value = (state == 'on')
    await db.update_setting('gpu_enabled', value)
    await update.message.reply_text(f"✅ GPU support set to: {state.upper()}")

@admin_only
async def config_ram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /config_ram [value] (e.g., 4g, 512m)")
        return
    
    value = context.args[0]
    await db.update_setting('default_ram', value)
    await update.message.reply_text(f"✅ Default RAM set to: {value}")

@admin_only
async def config_cpu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /config_cpu [number]")
        return
    
    try:
        value = int(context.args[0])
        await db.update_setting('default_cpu', value)
        await update.message.reply_text(f"✅ Default CPU threads set to: {value}")
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")

@admin_only
async def force_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /force_stop [user_id]")
        return
    
    try:
        target_id = int(context.args[0])
        container_data = await db.get_user_container(target_id)
        if not container_data:
            await update.message.reply_text("❌ User has no VM.")
            return
            
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, docker.stop_container, container_data['container_id'])

        if success:
            await db.update_container_status(target_id, "EXITED")
            await update.message.reply_text(f"🛑 Stopped VM for user {target_id}.")
        else:
            await update.message.reply_text("❌ Failed to stop VM.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.")

@admin_only
async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /maintenance [on|off]")
        return
    
    state = context.args[0].lower()
    if state not in ['on', 'off']:
        await update.message.reply_text("Invalid value. Use 'on' or 'off'.")
        return
    
    value = (state == 'on')
    await db.update_setting('maintenance_mode', value)
    
    if value:
        await update.message.reply_text("🚧 **Enabling Maintenance Mode...**\nStopping all active VMs.")
        
        # Stop all containers
        containers = await db.get_all_containers()
        loop = asyncio.get_running_loop()
        count = 0
        
        for c in containers:
            if c['status'] == 'RUNNING':
                success = await loop.run_in_executor(None, docker.stop_container, c['container_id'])
                if success:
                    await db.update_container_status(c['user_id'], "EXITED")
                    count += 1
        
        await update.message.reply_text(f"✅ Maintenance Mode ON. Stopped {count} VMs.")
    else:
        await update.message.reply_text("✅ Maintenance Mode OFF. Users can now create and start VMs.")

@admin_only
async def force_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /force_destroy [user_id|all]")
        return
    
    target = context.args[0]
    loop = asyncio.get_running_loop()

    if target.lower() == 'all':
        await update.message.reply_text("⚠️ **DESTROYING ALL VMs...** This cannot be undone.")
        containers = await db.get_all_containers()
        count = 0
        
        for c in containers:
            success = await loop.run_in_executor(None, docker.remove_container, c['container_id'])
            if success:
                await db.delete_container(c['user_id'])
                count += 1
            else:
                # Even if docker remove fails (e.g. container gone), remove from DB
                await db.delete_container(c['user_id'])
                count += 1
        
        await update.message.reply_text(f"✅ Destroyed {count} VMs.")
        return

    try:
        target_id = int(target)
        container_data = await db.get_user_container(target_id)
        if not container_data:
            await update.message.reply_text("❌ User has no VM.")
            return
            
        success = await loop.run_in_executor(None, docker.remove_container, container_data['container_id'])
        
        if success:
            await db.delete_container(target_id)
            await update.message.reply_text(f"✅ Destroyed VM for user {target_id}.")
        else:
            await db.delete_container(target_id)
            await update.message.reply_text(f"⚠️ Container removal failed, but removed from DB for user {target_id}.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID. Use a number or 'all'.")

# --- Main ---

if __name__ == '__main__':
    if not TOKEN:
        logger.error("Error: TELEGRAM_BOT_TOKEN not found in .env")
        exit(1)

    # Initialize DB
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.init_db())
    
    # Build Docker Image (skip if running inside container)
    logger.info("Checking Docker image...")
    try:
        # Check if we're running inside a container
        import os
        if os.path.exists('/.dockerenv') or os.path.exists('/proc/1/cgroup'):
            logger.info("Running inside container, skipping image build...")
        else:
            if not docker.build_image():
                logger.error("Failed to build Docker image. Exiting.")
                exit(1)
    except Exception as e:
        logger.error(f"Failed to build Docker image: {e}. Exiting.")
        exit(1)

    application = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('create', create_vm))
    application.add_handler(CommandHandler('status', status_vm))
    application.add_handler(CommandHandler('stop', stop_vm))
    application.add_handler(CommandHandler('start_vm', start_vm_command))
    application.add_handler(CommandHandler('destroy', destroy_vm))
    application.add_handler(CommandHandler('exec', exec_cmd))
    application.add_handler(CommandHandler('web_terminal', web_terminal))
    
    # Admin Handlers
    application.add_handler(CommandHandler('admin_info', admin_info))
    application.add_handler(CommandHandler('config_gpu', config_gpu))
    application.add_handler(CommandHandler('config_ram', config_ram))
    application.add_handler(CommandHandler('config_cpu', config_cpu))
    application.add_handler(CommandHandler('force_stop', force_stop))
    application.add_handler(CommandHandler('maintenance', maintenance))
    application.add_handler(CommandHandler('force_destroy', force_destroy))

    logger.info("Bot is running...")
    application.run_polling()