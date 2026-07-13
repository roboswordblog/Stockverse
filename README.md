# Stockverse
This is a game where you can invest in in real life stocks to simulate what would happen by using real life api data.

## Render deployment

This repo now includes a `render.yaml` Blueprint for Render.

Required settings:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Environment variable: `DATABASE_URL` (your Neon connection string)
- Environment variable: `FINNHUB_API_KEY`
- Environment variable: `FLASK_SECRET_KEY` (set this yourself to one fixed random value and keep it stable)
- Environment variable: `STOCKVERSE_DATA_DIR=/tmp/stockverse`

Important:

- The app now uses Neon Postgres when `DATABASE_URL` is set.
- SQLite remains available as a local fallback when `DATABASE_URL` is not set.
- `STOCKVERSE_DATA_DIR` is only for the market cache file and local SQLite fallback data.
