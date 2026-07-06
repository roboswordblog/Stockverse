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
            cursor.execute(
                """
                CREATE TABLE user_trades (
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


def get_user_holdings(username: str) -> list[dict]:
    create_user_database()
    with _connect() as connection:
        cursor = connection.cursor()
        cursor.execute(
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
            """
            INSERT INTO user_trades (username, symbol, shares, remaining_shares, bought_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, symbol, shares, shares, round(price, 2)),
        )
        cursor.execute(
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
        cursor.execute(
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

        cursor.execute("SELECT money FROM users WHERE username = ?", (username,))
        money_row = cursor.fetchone()
        if not money_row:
            return False, "User not found."
        current_money = float(money_row[0])

        cursor.execute(
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
            cursor.execute(
                """
                INSERT INTO user_trades (username, symbol, shares, remaining_shares, bought_price)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, symbol, owned_shares, owned_shares, round(average_price, 2)),
            )
            cursor.execute(
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
                cursor.execute(
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
                cursor.execute(
                    """
                    INSERT INTO user_trades (
                        username, symbol, shares, remaining_shares, bought_price, bought_at, sold_price, sold_at
                    )
                    VALUES (?, ?, ?, 0, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (username, symbol, sold_shares, round(float(bought_price), 2), bought_at, round(price, 2)),
                )
                cursor.execute(
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
            cursor.execute(
                """
                UPDATE user_holdings
                SET shares = ?
                WHERE username = ? AND symbol = ?
                """,
                (new_share_total, username, symbol),
            )
        else:
            cursor.execute(
                "DELETE FROM user_holdings WHERE username = ? AND symbol = ?",
                (username, symbol),
            )

        proceeds = round(shares * price, 2)
        cursor.execute(
            "UPDATE users SET money = ? WHERE username = ?",
            (round(current_money + proceeds, 2), username),
        )
        connection.commit()
        return True, "Sold successfully."
