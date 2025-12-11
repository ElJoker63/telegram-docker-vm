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
                status TEXT,
                plan_id INTEGER DEFAULT 1
            )
        """)

        # Migration: Add plan_id column if it doesn't exist
        try:
            await db.execute("ALTER TABLE containers ADD COLUMN plan_id INTEGER DEFAULT 1")
        except Exception:
            pass # Column likely already exists

        # Create allowed_users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                plan_id INTEGER DEFAULT 1,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add plan_id column if it doesn't exist
        try:
            await db.execute("ALTER TABLE allowed_users ADD COLUMN plan_id INTEGER DEFAULT 1")
        except Exception:
            pass # Column likely already exists

        # Create vm_plans table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vm_plans (
                id INTEGER PRIMARY KEY,
                name TEXT,
                ram TEXT,
                cpu INTEGER,
                disk TEXT,
                description TEXT
            )
        """)

        # Insert default plans if not exists
        plans = [
            (1, "Basic", "2g", 1, "100g", "2 GB RAM + 1 CPU + 100 GB"),
            (2, "Standard", "4g", 2, "150g", "4 GB RAM + 2 CPU + 150 GB"),
            (3, "Pro", "8g", 4, "250g", "8 GB RAM + 4 CPU + 250 GB"),
            (4, "Enterprise", "16g", 4, "500g", "16 GB RAM + 4 CPU + 500 GB")
        ]

        for plan in plans:
            await db.execute("""
                INSERT OR IGNORE INTO vm_plans (id, name, ram, cpu, disk, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, plan)

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

async def register_container(user_id, container_id, container_name, ssh_port, status="UP", plan_id=1):
    """Register a new container for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO containers (user_id, container_id, container_name, ssh_port, status, plan_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, container_id, container_name, ssh_port, status, plan_id))
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

async def add_allowed_user(user_id, username=None, plan_id=1, added_by=None):
    """Add a user to the allowed users list with a specific plan."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO allowed_users (user_id, username, plan_id, added_by)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, plan_id, added_by))
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

async def get_user_plan(user_id):
    """Get the plan assigned to a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT plan_id FROM allowed_users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row['plan_id'] if row else 1  # Default to plan 1 if not found

async def get_allowed_users():
    """Get all allowed users."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM allowed_users ORDER BY added_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

# --- VM Plans Management ---

async def get_vm_plans():
    """Get all available VM plans."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM vm_plans ORDER BY id") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_vm_plan(plan_id):
    """Get a specific VM plan by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM vm_plans WHERE id = ?", (plan_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None