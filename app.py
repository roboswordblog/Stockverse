from flask import Flask, jsonify, render_template, request
from database import create_user_database, login_user, signup_user, username_exists
from dataCollection import get_top_100_stocks

app = Flask(__name__)
create_user_database()

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

    return jsonify({'ok': True})

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/getAllPrices')
def getAllPrices():
    stocks = get_top_100_stocks()
    if stocks is None:
        return jsonify({'status': 'loading', 'stocks': []})
    return jsonify({'status': 'ready', 'stocks': stocks})

@app.route('/getStockStats')
def getStockStats():
    pass

if __name__ == '__main__':
    app.run(debug=True)
