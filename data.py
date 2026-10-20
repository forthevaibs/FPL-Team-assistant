"""Public FPL reads with timestamped SQLite snapshots and explicit stale fallback."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import requests

DB = Path(__file__).parent / 'data' / 'snapshots.sqlite'
BASE = 'https://fantasy.premierleague.com/api/'

def fetch(endpoint, refresh=False):
    DB.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as con:
        con.execute('CREATE TABLE IF NOT EXISTS snapshots(endpoint TEXT, fetched TEXT, payload TEXT, PRIMARY KEY(endpoint,fetched))')
        row = con.execute('SELECT fetched,payload FROM snapshots WHERE endpoint=? ORDER BY fetched DESC LIMIT 1', (endpoint,)).fetchone()
        now = datetime.now(timezone.utc)
        if row and not refresh and (now-datetime.fromisoformat(row[0])).total_seconds() < 3600:
            return json.loads(row[1]), row[0], False
        try:
            response = requests.get(BASE+endpoint, timeout=25, headers={'User-Agent':'FPLAdvisor/0.1'})
            response.raise_for_status()
            payload = response.json()
            if endpoint == 'bootstrap-static/' and not all(k in payload for k in ('elements','teams','events')):
                raise ValueError('Unexpected player data schema')
            if endpoint == 'fixtures/' and not isinstance(payload, list):
                raise ValueError('Unexpected fixture data schema')
            stamp = now.isoformat()
            con.execute('INSERT INTO snapshots VALUES(?,?,?)', (endpoint,stamp,json.dumps(payload)))
            return payload, stamp, False
        except (requests.RequestException, ValueError):
            if row:
                return json.loads(row[1]), row[0], True
            raise
