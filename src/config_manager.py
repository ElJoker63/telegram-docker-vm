import aiosqlite
import os
import logging

DB_PATH = os.path.join("data", "bot_data.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Create settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                gpu_enabled BOOLEAN DEFAULT 0,
                default_ram TEXT DEFAULT '2g',
                default_cpu INTEGER DEFAULT 2,
                maintenance_mode BOOLEAN DEFAULT 0
            )
        """)
        
        # Migration: Add maintenance_mode column if it doesn't exist (for existing DBs)
        # We do this BEFORE the insert to ensure the schema is correct
        try:
            await db.execute("ALTER TABLE settings ADD COLUMN maintenance_mode BOOLEAN DEFAULT 0")
        except Exception:
            pass # Column likely already exists

        # Insert default settings if not exists
        await db.execute("""
            INSERT OR IGNORE INTO settings (id, gpu_enabled, default_ram, default_cpu, maintenance_mode)
            VALUES (1, 0, '2g', 2, 0)
        """)

        # Create containers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS containers (
                user_id INTEGER PRIMARY KEY,
                container_id TEXT,
                container_name TEXT,
                ssh_port INTEGER,
                status TEXT
            )
        """)

        # Create allowed_users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()
    logger.info("Database initialized.")

async def get_settings():
    """Retrieve global settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_setting(key, value):
    """Update a specific setting (gpu_enabled, default_ram, default_cpu, maintenance_mode)."""
    allowed_keys = ["gpu_enabled", "default_ram", "default_cpu", "maintenance_mode"]
    if key not in allowed_keys:
        raise ValueError(f"Invalid setting key: {key}")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE settings SET {key} = ? WHERE id = 1", (value,))
        await db.commit()

async def register_container(user_id, container_id, container_name, ssh_port, status="UP"):
    """Register a new container for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO containers (user_id, container_id, container_name, ssh_port, status)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, container_id, container_name, ssh_port, status))
        await db.commit()

async def get_user_container(user_id):
    """Get container details for a specific user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM containers WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_container_status(user_id, status):
    """Update the status of a user's container."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE containers SET status = ? WHERE user_id = ?", (status, user_id))
        await db.commit()

async def delete_container(user_id):
    """Remove a container record from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM containers WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_all_containers():
    """Get all registered containers (for admin)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM containers") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

# --- Allowed Users Management ---

async def add_allowed_user(user_id, username=None, added_by=None):
    """Add a user to the allowed users list."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO allowed_users (user_id, username, added_by)
            VALUES (?, ?, ?)
        """, (user_id, username, added_by))
        await db.commit()

async def remove_allowed_user(user_id):
    """Remove a user from the allowed users list."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
        await db.commit()

async def is_user_allowed(user_id):
    """Check if a user is in the allowed users list."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None

async def get_allowed_users():
    """Get all allowed users."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM allowed_users ORDER BY added_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]