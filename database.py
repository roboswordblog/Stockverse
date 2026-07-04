import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stockverse.db"


def create_user_database() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new_database = not DB_PATH.exists()

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        if is_new_database:
            cursor.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    money REAL NOT NULL DEFAULT 1000.00
                )
                """
            )
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    money REAL NOT NULL DEFAULT 1000.00
                )
                """
            )

            cursor.execute("PRAGMA table_info(users)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            if "password" not in existing_columns:
                cursor.execute("ALTER TABLE users ADD COLUMN password TEXT")
            if "money" not in existing_columns:
                cursor.execute("ALTER TABLE users ADD COLUMN money REAL NOT NULL DEFAULT 1000.00")

        connection.commit()

    return DB_PATH


def username_exists(username: str) -> bool:
    create_user_database()
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return cursor.fetchone() is not None


def signup_user(username: str, password: str) -> bool:
    create_user_database()
    if username_exists(username):
        return False

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, money) VALUES (?, ?, ?)",
            (username, password, 1000.00),
        )
        connection.commit()
    return True


def login_user(username: str, password: str) -> bool:
    create_user_database()
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM users WHERE username = ? AND password = ?",
            (username, password),
        )
        return cursor.fetchone() is not None
