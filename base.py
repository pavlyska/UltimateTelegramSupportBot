from config import *

# Подключение к базе данных
conn = sqlite3.connect("botsupport_bot.db", check_same_thread=False) 
cursor = conn.cursor()

#######
# Создание таблиц в базе данных
#######
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_blocked BOOLEAN DEFAULT 0,
    block_reason TEXT,
    last_appeal_date DATE
)
""")

# Добавление недостающих колонок в таблицу users
cursor.execute("PRAGMA table_info(users)")
columns = [column[1] for column in cursor.fetchall()]
if 'is_blocked' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT 0")
if 'block_reason' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN block_reason TEXT")
if 'last_appeal_date' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN last_appeal_date DATE")
conn.commit()

# Создание остальных таблиц
cursor.execute("""
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    status TEXT DEFAULT 'open',
    assigned_to INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP DEFAULT NULL,
    close_reason TEXT
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS staff (
    user_id INTEGER PRIMARY KEY,
    role TEXT
)
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS appeals (
        appeal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'pending',
        related_ticket_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()