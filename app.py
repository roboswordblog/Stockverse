import hashlib
import os
from datetime import timedelta
from pathlib import Path

def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent / "api.env"
    if not env_path.exists():
        return

    try:
        with env_path.open("r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip()
    except OSError:
        return


_load_local_env()

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from database import (
    buy_stock,
    change_password,
    change_username,
    create_user_database,
    delete_account,
    follow_stock,
    get_followed_symbols,
    get_user_holding,
    get_user_holdings,
    get_user_money,
    list_users,
    login_user,
    reset_account,
    sell_stock,
    signup_user,
    unfollow_stock,
    username_exists,
)
from dataCollection import (
    get_market_last_refresh,
    get_market_status,
    get_stock_history,
    get_stock_profile,
    get_stock_quote,
    get_top_100_stocks,
    search_stocks,
)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "stockverse-dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=30)
create_user_database()


def _login_user_session(username: str) -> None:
    session["username"] = username
    session.permanent = True


def _current_username() -> str | None:
    username = session.get("username")
    return username.strip() if isinstance(username, str) and username.strip() else None


def _position_snapshot(holding: dict | None, stock_info: dict | None) -> dict:
    shares = int((holding or {}).get("shares") or 0)
    average_price = float((holding or {}).get("average_price") or 0)
    current_price = float((stock_info or {}).get("price") or 0)
    market_value = round(shares * current_price, 2)
    cost_basis = round(shares * average_price, 2)
    unrealized_change = round(market_value - cost_basis, 2)
    unrealized_change_percent = round((unrealized_change / cost_basis) * 100, 2) if cost_basis else 0.0
    return {
        "shares": shares,
        "average_price": round(average_price, 2),
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_change": unrealized_change,
        "unrealized_change_percent": unrealized_change_percent,
    }


def _build_leaderboard(current_username: str | None, stock_map: dict[str, dict]) -> dict:
    user_rows = list_users()
    if not user_rows:
        return {"leaders": [], "current_user": None}

    portfolio_rows = []
    for user in user_rows:
        holdings = get_user_holdings(user["username"])
        total_holdings_value = 0.0
        open_positions = 0
        for holding in holdings:
            stock_info = stock_map.get(holding["symbol"]) or get_stock_quote(holding["symbol"]) or {}
            total_holdings_value += holding["shares"] * float(stock_info.get("price") or 0)
            open_positions += 1

        cash = float(user["money"] or 0)
        total_value = round(cash + total_holdings_value, 2)
        total_return = round(total_value - 1000.0, 2)
        return_percent = round((total_return / 1000.0) * 100, 2)
        portfolio_rows.append(
            {
                "username": user["username"],
                "cash": round(cash, 2),
                "equity": round(total_holdings_value, 2),
                "total_value": total_value,
                "total_return": total_return,
                "return_percent": return_percent,
                "open_positions": open_positions,
            }
        )

    portfolio_rows.sort(
        key=lambda row: (row["total_value"], row["return_percent"], row["username"].lower()),
        reverse=True,
    )
    for index, row in enumerate(portfolio_rows, start=1):
        row["rank"] = index

    current_user_row = next((row for row in portfolio_rows if row["username"] == current_username), None)
    return {
        "leaders": portfolio_rows[:8],
        "current_user": current_user_row,
    }


def _static_version(path: str) -> int:
    if not app.static_folder:
        return "1"
    file_path = os.path.join(app.static_folder, path)
    try:
        with open(file_path, "rb") as file_handle:
            return hashlib.sha1(file_handle.read()).hexdigest()[:12]
    except OSError:
        return "1"


@app.context_processor
def inject_static_version():
    return {"static_version": _static_version}


@app.route('/')
def index():
    username = _current_username()
    if username:
        return redirect(url_for("home"))
    return render_template('index.html', initial_section='index')


@app.route('/login', methods=['GET'])
def login_page():
    username = _current_username()
    if username:
        return redirect(url_for("home"))
    return render_template('index.html', initial_section='login')


@app.route('/signup', methods=['GET'])
def signup_page():
    username = _current_username()
    if username:
        return redirect(url_for("home"))
    return render_template('index.html', initial_section='signup')


@app.route('/guide')
def guide():
    username = _current_username()
    return render_template(
        'guide.html',
        username=username,
        home_target=url_for("home") if username else url_for("index"),
    )

@app.route('/usernameThere')
def username_there():
    username = (request.args.get('username') or '').strip()
    if not username:
        return jsonify({'exists': False})
    return jsonify({'exists': username_exists(username)})


@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username and password are required.'}), 400

    if username_exists(username):
        return jsonify({'ok': False, 'error': 'Username is already taken.'}), 409

    created = signup_user(username, password)
    if not created:
        return jsonify({'ok': False, 'error': 'Unable to create account.'}), 500

    _login_user_session(username)
    return jsonify({'ok': True, 'username': username, 'redirect_url': url_for("home")})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username and password are required.'}), 400

    if not login_user(username, password):
        return jsonify({'ok': False, 'error': 'Invalid username or password.'}), 401

    _login_user_session(username)
    return jsonify({'ok': True, 'username': username, 'redirect_url': url_for("home")})


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True, 'redirect_url': url_for("index")})

@app.route('/home')
def home():
    username = _current_username()
    if not username:
        return redirect(url_for("login_page"))
    return render_template('home.html', username=username)


@app.route('/profile')
def profile():
    username = _current_username()
    if not username:
        return redirect(url_for("login_page"))
    return render_template('profile.html', username=username, balance=get_user_money(username))

@app.route('/getAllPrices')
def getAllPrices():
    stocks = get_top_100_stocks()
    market_status = get_market_status()
    if stocks is None:
        return jsonify({'status': 'loading', 'stocks': [], 'updated_at': get_market_last_refresh(), 'market_status': market_status})
    return jsonify({'status': 'ready', 'stocks': stocks, 'updated_at': get_market_last_refresh(), 'market_status': market_status})

@app.route('/api/home/overview')
def home_overview():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    stocks = get_top_100_stocks() or []
    top_ten = stocks[:10]
    followed_symbols = set(get_followed_symbols(username))
    followed = [stock for stock in stocks if stock["symbol"] in followed_symbols]
    stock_map = {stock["symbol"]: stock for stock in stocks}
    holdings = []
    for holding in get_user_holdings(username):
        stock_info = stock_map.get(holding["symbol"]) or get_stock_quote(holding["symbol"]) or {}
        current_price = float(stock_info.get("price") or 0)
        change_value = round(current_price - holding["average_price"], 2) if current_price else 0.0
        percent_change = round((change_value / holding["average_price"]) * 100, 2) if holding["average_price"] else 0.0
        holdings.append(
            {
                **holding,
                "current_price": round(current_price, 2),
                "position_value": round(current_price * holding["shares"], 2),
                "position_change": change_value,
                "position_change_percent": percent_change,
            }
        )

    return jsonify(
        {
            "ok": True,
            "username": username,
            "balance": get_user_money(username),
            "updated_at": get_market_last_refresh(),
            "market_status": get_market_status(),
            "top_stocks": [
                {**stock, "followed": stock["symbol"] in followed_symbols}
                for stock in top_ten
            ],
            "followed_stocks": followed,
            "holdings": holdings,
            "leaderboard": _build_leaderboard(username, stock_map),
        }
    )

@app.route('/api/follow', methods=['POST'])
def follow():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    action = (data.get("action") or "follow").strip().lower()
    if not symbol:
        return jsonify({"ok": False, "error": "Symbol is required."}), 400

    if action == "unfollow":
        unfollow_stock(username, symbol)
        return jsonify({"ok": True, "followed": False})

    follow_stock(username, symbol)
    return jsonify({"ok": True, "followed": True})

@app.route('/getStockStats')
def getStockStats():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"ok": False, "error": "Symbol is required."}), 400

    quote = get_stock_quote(symbol)
    if quote is None:
        return jsonify({"ok": False, "error": "Unable to load stock data."}), 503

    profile = get_stock_profile(symbol) or {}
    followed = symbol in set(get_followed_symbols(username))
    holding = get_user_holding(username, symbol)
    return jsonify(
        {
            "ok": True,
            "stock": {
                **quote,
                "name": profile.get("name", symbol),
                "exchange": profile.get("exchange", "Unknown"),
                "industry": profile.get("industry", "Unknown"),
                "country": profile.get("country", "Unknown"),
                "followed": followed,
            },
            "balance": get_user_money(username),
            "position": _position_snapshot(holding, quote),
            "market_status": get_market_status(),
        }
    )


@app.route('/api/stock-history')
def stock_history():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"ok": False, "error": "Symbol is required."}), 400

    range_key = (request.args.get("range") or "1M").strip().upper()
    history = get_stock_history(symbol, range_key)
    return jsonify({"ok": True, "history": history, "market_status": get_market_status()})

@app.route('/api/buy', methods=['POST'])
def buy():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    shares = int(data.get("shares") or 0)
    quote = get_stock_quote(symbol) if symbol else None
    price = float((quote or {}).get("price") or 0)
    if not symbol or shares <= 0 or price <= 0:
        return jsonify({"ok": False, "error": "Invalid order."}), 400

    success, message = buy_stock(username, symbol, shares, price)
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True, "message": message, "balance": get_user_money(username)})

@app.route('/api/sell', methods=['POST'])
def sell():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    shares = int(data.get("shares") or 0)
    quote = get_stock_quote(symbol) if symbol else None
    price = float((quote or {}).get("price") or 0)
    if not symbol or shares <= 0 or price <= 0:
        return jsonify({"ok": False, "error": "Invalid order."}), 400

    success, message = sell_stock(username, symbol, shares, price)
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True, "message": message, "balance": get_user_money(username)})

@app.route('/api/search-stocks')
def search_stock_list():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    query = (request.args.get("q") or "").strip()
    return jsonify({"ok": True, "results": search_stocks(query)})


@app.route('/api/account')
def account_details():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    return jsonify(
        {
            "ok": True,
            "username": username,
            "balance": get_user_money(username),
        }
    )


@app.route('/api/account/username', methods=['POST'])
def account_change_username():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    new_username = (data.get("new_username") or "").strip()
    if len(new_username) < 3:
        return jsonify({"ok": False, "error": "Username must be at least 3 characters."}), 400

    success, message = change_username(username, password, new_username)
    if not success:
        return jsonify({"ok": False, "error": message}), 400

    _login_user_session(new_username)
    return jsonify({"ok": True, "message": message, "username": new_username})


@app.route('/api/account/password', methods=['POST'])
def account_change_password():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()
    if len(new_password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters."}), 400

    success, message = change_password(username, current_password, new_password)
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True, "message": message})


@app.route('/api/account/reset', methods=['POST'])
def account_reset():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    success, message = reset_account(username, password)
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    return jsonify({"ok": True, "message": message, "balance": get_user_money(username)})


@app.route('/api/account/delete', methods=['POST'])
def account_delete():
    username = _current_username()
    if not username:
        return jsonify({"ok": False, "error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    success, message = delete_account(username, password)
    if not success:
        return jsonify({"ok": False, "error": message}), 400

    session.clear()
    return jsonify({"ok": True, "message": message, "redirect_url": url_for("index")})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
