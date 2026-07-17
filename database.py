import os
import sqlite3
import threading
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - optional for local sqlite fallback
    psycopg = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("STOCKVERSE_DATA_DIR", str(BASE_DIR / "data"))).expanduser()
DB_PATH = DATA_DIR / "stockverse.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
_schema_lock = threading.Lock()
_schema_initialized = False


def _normalize_query(query: str) -> str:
    if USE_POSTGRES:
        return query.replace("?", "%s")
    return query


def _execute(cursor, query: str, params: tuple = ()):
    cursor.execute(_normalize_query(query), params)


def _connect():
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is set.")
        return psycopg.connect(DATABASE_URL)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _create_sqlite_schema(cursor) -> None:
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            shares INTEGER NOT NULL,
            remaining_shares INTEGER NOT NULL,
            bought_price REAL NOT NULL,
            bought_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sold_price REAL,
            sold_at DATETIME
        )
        """
    )


def _create_postgres_schema(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL DEFAULT '',
            money DOUBLE PRECISION NOT NULL DEFAULT 1000.00
        )
        """
    )
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password TEXT NOT NULL DEFAULT ''")
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS money DOUBLE PRECISION NOT NULL DEFAULT 1000.00")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_follows (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            UNIQUE(username, symbol)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_holdings (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            shares INTEGER NOT NULL DEFAULT 0,
            average_price DOUBLE PRECISION NOT NULL DEFAULT 0,
            UNIQUE(username, symbol)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_trades (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            symbol TEXT NOT NULL,
            shares INTEGER NOT NULL,
            remaining_shares INTEGER NOT NULL,
            bought_price DOUBLE PRECISION NOT NULL,
            bought_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sold_price DOUBLE PRECISION,
            sold_at TIMESTAMPTZ
        )
        """
    )


def create_user_database() -> str | Path:
    global _schema_initialized
    if _schema_initialized:
        return DATABASE_URL if USE_POSTGRES else DB_PATH

    with _schema_lock:
        if _schema_initialized:
            return DATABASE_URL if USE_POSTGRES else DB_PATH

        with _connect() as connection:
            cursor = connection.cursor()
            if USE_POSTGRES:
                _create_postgres_schema(cursor)
                connection.commit()
                _schema_initialized = True
                return DATABASE_URL

            _create_sqlite_schema(cursor)
            connection.commit()
            _schema_initialized = True
            return DB_PATH


def username_exists(username: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(cursor, "SELECT 1 FROM users WHERE username = ?", (username,))
        return cursor.fetchone() is not None


def signup_user(username: str, password: str) -> bool:
    create_user_database()
    if username_exists(username):
        return False

    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "INSERT INTO users (username, password, money) VALUES (?, ?, ?)",
            (username, password, 1000.00),
        )
        connection.commit()
    return True


def login_user(username: str, password: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "SELECT 1 FROM users WHERE username = ? AND password = ?",
            (username, password),
        )
        return cursor.fetchone() is not None


def change_username(current_username: str, password: str, new_username: str) -> tuple[bool, str]:
    create_user_database()
    normalized_username = new_username.strip()
    if not normalized_username:
        return False, "New username is required."
    if current_username == normalized_username:
        return False, "Choose a different username."
    if not login_user(current_username, password):
        return False, "Current password is incorrect."
    if username_exists(normalized_username):
        return False, "Username is already taken."

    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "UPDATE users SET username = ? WHERE username = ?",
            (normalized_username, current_username),
        )
        if cursor.rowcount == 0:
            return False, "User not found."

        for table_name in ("user_follows", "user_holdings", "user_trades"):
            _execute(
                cursor,
                f"UPDATE {table_name} SET username = ? WHERE username = ?",
                (normalized_username, current_username),
            )
        connection.commit()
    return True, "Username updated successfully."


def change_password(username: str, current_password: str, new_password: str) -> tuple[bool, str]:
    create_user_database()
    if not login_user(username, current_password):
        return False, "Current password is incorrect."
    if not new_password.strip():
        return False, "New password is required."

    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "UPDATE users SET password = ? WHERE username = ?",
            (new_password.strip(), username),
        )
        if cursor.rowcount == 0:
            return False, "User not found."
        connection.commit()
    return True, "Password updated successfully."


def reset_account(username: str, password: str) -> tuple[bool, str]:
    create_user_database()
    if not login_user(username, password):
        return False, "Current password is incorrect."

    with _connect() as connection:
        cursor = connection.cursor()
        for table_name in ("user_follows", "user_holdings", "user_trades"):
            _execute(cursor, f"DELETE FROM {table_name} WHERE username = ?", (username,))
        _execute(
            cursor,
            "UPDATE users SET money = ? WHERE username = ?",
            (1000.00, username),
        )
        if cursor.rowcount == 0:
            return False, "User not found."
        connection.commit()
    return True, "Account reset successfully."


def delete_account(username: str, password: str) -> tuple[bool, str]:
    create_user_database()
    if not login_user(username, password):
        return False, "Current password is incorrect."

    with _connect() as connection:
        cursor = connection.cursor()
        for table_name in ("user_follows", "user_holdings", "user_trades"):
            _execute(cursor, f"DELETE FROM {table_name} WHERE username = ?", (username,))
        _execute(cursor, "DELETE FROM users WHERE username = ?", (username,))
        if cursor.rowcount == 0:
            return False, "User not found."
        connection.commit()
    return True, "Account deleted successfully."


def get_user_money(username: str) -> float | None:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(cursor, "SELECT money FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return float(row[0]) if row else None


def get_followed_symbols(username: str) -> list[str]:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "SELECT symbol FROM user_follows WHERE username = ? ORDER BY symbol ASC",
            (username,),
        )
        return [row[0] for row in cursor.fetchall()]


def get_user_holdings(username: str) -> list[dict]:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            """
            SELECT symbol, shares, average_price
            FROM user_holdings
            WHERE username = ? AND shares > 0
            ORDER BY symbol ASC
            """,
            (username,),
        )
        return [
            {
                "symbol": row[0],
                "shares": int(row[1]),
                "average_price": round(float(row[2]), 2),
            }
            for row in cursor.fetchall()
        ]


def get_user_holding(username: str, symbol: str) -> dict | None:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            """
            SELECT symbol, shares, average_price
            FROM user_holdings
            WHERE username = ? AND symbol = ?
            """,
            (username, symbol),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "symbol": row[0],
            "shares": int(row[1]),
            "average_price": round(float(row[2]), 2),
        }


def list_users() -> list[dict]:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        if USE_POSTGRES:
            cursor.execute(
                """
                SELECT username, money
                FROM users
                ORDER BY LOWER(username) ASC, username ASC
                """
            )
        else:
            cursor.execute(
                """
                SELECT username, money
                FROM users
                ORDER BY username COLLATE NOCASE ASC
                """
            )
        return [
            {
                "username": row[0],
                "money": round(float(row[1]), 2),
            }
            for row in cursor.fetchall()
        ]


def follow_stock(username: str, symbol: str) -> bool:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        if USE_POSTGRES:
            cursor.execute(
                """
                INSERT INTO user_follows (username, symbol)
                VALUES (%s, %s)
                ON CONFLICT (username, symbol) DO NOTHING
                """,
                (username, symbol),
            )
        else:
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
        _execute(
            cursor,
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
        _execute(cursor, "SELECT money FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return False, "User not found."

        current_money = float(user_row[0])
        if current_money < total_cost:
            return False, "Not enough balance."

        _execute(
            cursor,
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
            _execute(
                cursor,
                """
                UPDATE user_holdings
                SET shares = ?, average_price = ?
                WHERE username = ? AND symbol = ?
                """,
                (new_total_shares, new_average, username, symbol),
            )
        else:
            _execute(
                cursor,
                """
                INSERT INTO user_holdings (username, symbol, shares, average_price)
                VALUES (?, ?, ?, ?)
                """,
                (username, symbol, shares, round(price, 2)),
            )

        _execute(
            cursor,
            """
            INSERT INTO user_trades (username, symbol, shares, remaining_shares, bought_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, symbol, shares, shares, round(price, 2)),
        )
        _execute(
            cursor,
            "UPDATE users SET money = ? WHERE username = ?",
            (round(current_money - total_cost, 2), username),
        )
        connection.commit()
        return True, "Bought successfully."


def sell_stock(username: str, symbol: str, shares: int, price: float) -> tuple[bool, str]:
    if shares <= 0 or price <= 0:
        return False, "Invalid order."

    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        _execute(
            cursor,
            "SELECT shares, average_price FROM user_holdings WHERE username = ? AND symbol = ?",
            (username, symbol),
        )
        holding = cursor.fetchone()
        if not holding:
            return False, "You do not own this stock."

        owned_shares = int(holding[0])
        average_price = float(holding[1])
        if shares > owned_shares:
            return False, "Not enough shares to sell."

        _execute(cursor, "SELECT money FROM users WHERE username = ?", (username,))
        money_row = cursor.fetchone()
        if not money_row:
            return False, "User not found."
        current_money = float(money_row[0])

        _execute(
            cursor,
            """
            SELECT id, shares, remaining_shares, bought_price, bought_at
            FROM user_trades
            WHERE username = ? AND symbol = ? AND remaining_shares > 0
            ORDER BY bought_at ASC, id ASC
            """,
            (username, symbol),
        )
        open_lots = cursor.fetchall()

        if not open_lots:
            _execute(
                cursor,
                """
                INSERT INTO user_trades (username, symbol, shares, remaining_shares, bought_price)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, symbol, owned_shares, owned_shares, round(average_price, 2)),
            )
            _execute(
                cursor,
                """
                SELECT id, shares, remaining_shares, bought_price, bought_at
                FROM user_trades
                WHERE username = ? AND symbol = ? AND remaining_shares > 0
                ORDER BY bought_at ASC, id ASC
                """,
                (username, symbol),
            )
            open_lots = cursor.fetchall()

        shares_to_sell = shares
        for trade_id, lot_shares, remaining_shares, bought_price, bought_at in open_lots:
            if shares_to_sell <= 0:
                break

            lot_remaining = int(remaining_shares)
            if lot_remaining <= shares_to_sell:
                _execute(
                    cursor,
                    """
                    UPDATE user_trades
                    SET remaining_shares = 0, sold_price = ?, sold_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (round(price, 2), trade_id),
                )
                shares_to_sell -= lot_remaining
            else:
                sold_shares = shares_to_sell
                _execute(
                    cursor,
                    """
                    INSERT INTO user_trades (
                        username, symbol, shares, remaining_shares, bought_price, bought_at, sold_price, sold_at
                    )
                    VALUES (?, ?, ?, 0, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (username, symbol, sold_shares, round(float(bought_price), 2), bought_at, round(price, 2)),
                )
                _execute(
                    cursor,
                    """
                    UPDATE user_trades
                    SET shares = ?, remaining_shares = ?
                    WHERE id = ?
                    """,
                    (int(lot_shares) - sold_shares, lot_remaining - sold_shares, trade_id),
                )
                shares_to_sell = 0

        new_share_total = owned_shares - shares
        if new_share_total > 0:
            _execute(
                cursor,
                """
                UPDATE user_holdings
                SET shares = ?
                WHERE username = ? AND symbol = ?
                """,
                (new_share_total, username, symbol),
            )
        else:
            _execute(
                cursor,
                "DELETE FROM user_holdings WHERE username = ? AND symbol = ?",
                (username, symbol),
            )

        proceeds = round(shares * price, 2)
        _execute(
            cursor,
            "UPDATE users SET money = ? WHERE username = ?",
            (round(current_money + proceeds, 2), username),
        )
        connection.commit()
        return True, "Sold successfully."
