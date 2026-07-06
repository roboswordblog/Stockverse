import os

from flask import Flask, jsonify, render_template, request, session
from database import (
    buy_stock,
    create_user_database,
    follow_stock,
    get_followed_symbols,
    get_user_holdings,
    get_user_money,
    login_user,
    sell_stock,
    signup_user,
    unfollow_stock,
    username_exists,
)
from dataCollection import get_stock_profile, get_stock_quote, get_top_100_stocks, search_stocks

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "stockverse-dev-secret")
create_user_database()


def _current_username() -> str | None:
    username = session.get("username")
    return username.strip() if isinstance(username, str) and username.strip() else None

@app.route('/')
def index():
    return render_template('index.html')

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

    session["username"] = username
    return jsonify({'ok': True})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username and password are required.'}), 400

    if not login_user(username, password):
        return jsonify({'ok': False, 'error': 'Invalid username or password.'}), 401

    session["username"] = username
    return jsonify({'ok': True})

@app.route('/home')
def home():
    username = _current_username()
    if not username:
        return render_template('index.html')
    return render_template('home.html', username=username)

@app.route('/getAllPrices')
def getAllPrices():
    stocks = get_top_100_stocks()
    if stocks is None:
        return jsonify({'status': 'loading', 'stocks': []})
    return jsonify({'status': 'ready', 'stocks': stocks})

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
            "top_stocks": [
                {**stock, "followed": stock["symbol"] in followed_symbols}
                for stock in top_ten
            ],
            "followed_stocks": followed,
            "holdings": holdings,
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
        }
    )

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

if __name__ == '__main__':
    app.run(debug=True)
