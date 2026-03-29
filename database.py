import sqlite3
import os

# Database file path (data folder inside your project directory)
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'users.db')

def get_db():
    """Return a database connection with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(owner_id=None):
    """Initialize database: create tables if not exist, and add owner as admin if provided."""
    # Ensure the 'data' directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with get_db() as conn:
        # Users table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                preferred_image_style TEXT DEFAULT 'photorealistic'
            )
        ''')
        # Admins table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        # Conversations table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Add owner as admin if owner_id provided
        if owner_id:
            conn.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (owner_id,))

def add_user(user_id, username, first_name, last_name):
    """Add a new user or update existing user's info and set last_active."""
    with get_db() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_active)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, username, first_name, last_name))

def update_last_active(user_id):
    """Update the last_active timestamp for a user."""
    with get_db() as conn:
        conn.execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))

def get_all_users():
    """Return all users as list of rows."""
    with get_db() as conn:
        return conn.execute('SELECT * FROM users').fetchall()

def get_user_count():
    """Return total number of users."""
    with get_db() as conn:
        return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]

def get_active_users(days=7):
    """Return number of users active within the last 'days' days."""
    with get_db() as conn:
        return conn.execute('SELECT COUNT(*) FROM users WHERE last_active >= datetime("now", ?)', (f'-{days} days',)).fetchone()[0]

def is_admin(user_id):
    """Check if a user_id is in admins table."""
    with get_db() as conn:
        res = conn.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,)).fetchone()
        return res is not None

def add_admin(user_id):
    """Add a user as admin."""
    with get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (user_id,))

def remove_admin(user_id):
    """Remove a user from admins."""
    with get_db() as conn:
        conn.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))

def get_admins():
    """Return list of all admin user_ids."""
    with get_db() as conn:
        return [row['user_id'] for row in conn.execute('SELECT user_id FROM admins').fetchall()]

def add_conversation(user_id, role, message):
    """Store a conversation message (role: 'user' or 'assistant')."""
    with get_db() as conn:
        conn.execute('INSERT INTO conversations (user_id, role, message) VALUES (?, ?, ?)',
                     (user_id, role, message))

def get_conversation_history(user_id, limit=20):
    """Return last 'limit' messages for a user, ordered oldest to newest."""
    with get_db() as conn:
        rows = conn.execute('''
            SELECT role, message FROM conversations
            WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit)).fetchall()
    # Reverse to get chronological order (oldest first)
    return list(reversed(rows))

def clear_conversation_history(user_id):
    """Delete all conversation records for a user."""
    with get_db() as conn:
        conn.execute('DELETE FROM conversations WHERE user_id = ?', (user_id,))

def get_user_style(user_id):
    """Return preferred image style for a user, default 'photorealistic'."""
    with get_db() as conn:
        row = conn.execute('SELECT preferred_image_style FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return row['preferred_image_style'] if row else 'photorealistic'

def set_user_style(user_id, style):
    """Set preferred image style for a user."""
    with get_db() as conn:
        conn.execute('UPDATE users SET preferred_image_style = ? WHERE user_id = ?', (style, user_id))
