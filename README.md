# Stockverse
This is a game where you can invest in in real life stocks to simulate what would happen by using real life api data.

## Render deployment

This repo now includes a `render.yaml` Blueprint for Render.

Required settings:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Environment variable: `FINNHUB_API_KEY`
- Environment variable: `FLASK_SECRET_KEY` (the Blueprint can generate this)
- Environment variable: `STOCKVERSE_DATA_DIR=/var/data/stockverse`

Important:

- The app uses SQLite and a market cache file on disk.
- On Render, those files should live on a persistent disk or they will reset on redeploy/restart.
- The included Blueprint mounts a disk at `/var/data` and points the app at `/var/data/stockverse`.
