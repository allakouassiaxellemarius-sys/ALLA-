import json
import os
import time
from urllib.request import Request, urlopen

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

def _redis_cmd(method, *args):
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    body = json.dumps({"cmd": [method, *args]}).encode()
    req = Request(UPSTASH_URL, data=body, headers={
        "Authorization": f"Bearer {UPSTASH_TOKEN}",
        "Content-Type": "application/json"
    })
    try:
        resp = urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return data.get("result")
    except Exception:
        return None

def load_game(chat_id):
    raw = _redis_cmd("GET", f"game:{chat_id}")
    if raw:
        return json.loads(raw)
    return None

def save_game(chat_id, game):
    game["_updated"] = time.time()
    _redis_cmd("SET", f"game:{chat_id}", json.dumps(game, default=str))
    _redis_cmd("EXPIRE", f"game:{chat_id}", 86400)

def delete_game(chat_id):
    _redis_cmd("DEL", f"game:{chat_id}")
