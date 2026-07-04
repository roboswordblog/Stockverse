from flask import Flask, render_template, request
from database import create_user_database

app = Flask(__name__)
create_user_database()

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
