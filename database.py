import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "stockverse.db"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def create_user_database() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new_database = not DB_PATH.exists()

    with _connect() as connection:
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
            cursor.execute(
                """
                CREATE TABLE user_follows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    UNIQUE(username, symbol)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE user_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    shares INTEGER NOT NULL DEFAULT 0,
                    average_price REAL NOT NULL DEFAULT 0,
                    UNIQUE(username, symbol)
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

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_follows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    UNIQUE(username, symbol)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    shares INTEGER NOT NULL DEFAULT 0,
                    average_price REAL NOT NULL DEFAULT 0,
                    UNIQUE(username, symbol)
                )
                """
            )

        connection.commit()

    return DB_PATH


def username_exists(username: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return cursor.fetchone() is not None


def signup_user(username: str, password: str) -> bool:
    create_user_database()
    if username_exists(username):
        return False

    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, money) VALUES (?, ?, ?)",
            (username, password, 1000.00),
        )
        connection.commit()
    return True


def login_user(username: str, password: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT 1 FROM users WHERE username = ? AND password = ?",
            (username, password),
        )
        return cursor.fetchone() is not None


def get_user_money(username: str) -> float | None:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT money FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return float(row[0]) if row else None


def get_followed_symbols(username: str) -> list[str]:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT symbol FROM user_follows WHERE username = ? ORDER BY symbol ASC",
            (username,),
        )
        return [row[0] for row in cursor.fetchall()]


def follow_stock(username: str, symbol: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO user_follows (username, symbol) VALUES (?, ?)",
            (username, symbol),
        )
        connection.commit()
        return cursor.rowcount > 0


def unfollow_stock(username: str, symbol: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM user_follows WHERE username = ? AND symbol = ?",
            (username, symbol),
        )
        connection.commit()
        return cursor.rowcount > 0


def buy_stock(username: str, symbol: str, shares: int, price: float) -> tuple[bool, str]:
    if shares <= 0 or price <= 0:
        return False, "Invalid order."

    create_user_database()
    total_cost = round(shares * price, 2)

    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT money FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return False, "User not found."

        current_money = float(user_row[0])
        if current_money < total_cost:
            return False, "Not enough balance."

        cursor.execute(
            "SELECT shares, average_price FROM user_holdings WHERE username = ? AND symbol = ?",
            (username, symbol),
        )
        holding = cursor.fetchone()

        if holding:
            existing_shares = int(holding[0])
            existing_avg = float(holding[1])
            new_total_shares = existing_shares + shares
            new_average = round(
                ((existing_shares * existing_avg) + total_cost) / new_total_shares,
                2,
            )
            cursor.execute(
                """
                UPDATE user_holdings
                SET shares = ?, average_price = ?
                WHERE username = ? AND symbol = ?
                """,
                (new_total_shares, new_average, username, symbol),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_holdings (username, symbol, shares, average_price)
                VALUES (?, ?, ?, ?)
                """,
                (username, symbol, shares, round(price, 2)),
            )

        cursor.execute(
            "UPDATE users SET money = ? WHERE username = ?",
            (round(current_money - total_cost, 2), username),
        )
        connection.commit()
        return True, "Bought successfully."
