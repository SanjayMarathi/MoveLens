"""
Fetch a player's recent games from Chess.com or Lichess by username (both have free public APIs).

Only these two fixed hosts are ever contacted, and the username is validated first, so this cannot be used to
make the server fetch arbitrary URLs. Results are cached for a few minutes to be polite to the APIs.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
USER_AGENT = "MoveLens/1.0 (chess game review)"
MAX_BYTES = 12_000_000
CACHE_SECONDS = 180
GAME_LIMIT = 20

_cache: Dict[Tuple[str, str], Tuple[float, List[dict]]] = {}


class ImportProblem(Exception):
    """A problem to show to the user. `status` is the HTTP status the API should answer with."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _get(url: str, accept: str = "application/json") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ImportProblem("No player with that username was found.", 404)
        if e.code == 429:
            raise ImportProblem("The site is rate-limiting requests right now. Try again in a minute.", 429)
        raise ImportProblem(f"The site answered with an error ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ImportProblem("Could not reach the site. Check your connection and try again.")
    if len(data) > MAX_BYTES:
        raise ImportProblem("That player's archive is too large to read.")
    return data


def _header(pgn: str, key: str) -> Optional[str]:
    m = re.search(r'^\[' + key + r'\s+"([^"]*)"\]', pgn, re.MULTILINE)
    return m.group(1) if m else None


def _ending(pgn: str) -> str:
    result = _header(pgn, "Result") or "*"
    return {"1/2-1/2": "½-½"}.get(result, result)


def chesscom_games(username: str, fetch: Callable[..., bytes] = _get) -> List[dict]:
    base = f"https://api.chess.com/pub/player/{urllib.parse.quote(username)}/games/archives"
    archives = json.loads(fetch(base)).get("archives", [])
    games: List[dict] = []
    for url in reversed(archives[-3:]):                      # newest month first
        if not url.startswith("https://api.chess.com/pub/player/"):
            continue
        for g in json.loads(fetch(url)).get("games", []):
            pgn = g.get("pgn")
            if not pgn or g.get("rules", "chess") != "chess":
                continue
            games.append({
                "site": "chesscom", "url": g.get("url"), "pgn": pgn,
                "white": g["white"]["username"], "black": g["black"]["username"],
                "white_rating": g["white"].get("rating"), "black_rating": g["black"].get("rating"),
                "result": _ending(pgn), "time_class": g.get("time_class"), "rated": g.get("rated"),
                "played_at": g.get("end_time"),
            })
        if len(games) >= GAME_LIMIT * 2:
            break
    games.sort(key=lambda g: g["played_at"] or 0, reverse=True)
    return games[:GAME_LIMIT]


def _lichess_name(player: dict) -> str:
    user = player.get("user") or {}
    if user.get("name"):
        return user["name"]
    return "Stockfish" if player.get("aiLevel") else "Anonymous"


def lichess_games(username: str, fetch: Callable[..., bytes] = _get) -> List[dict]:
    url = (f"https://lichess.org/api/games/user/{urllib.parse.quote(username)}"
           f"?max={GAME_LIMIT}&pgnInJson=true&opening=true&clocks=true")
    games: List[dict] = []
    for line in fetch(url, accept="application/x-ndjson").decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        if g.get("variant", "standard") != "standard" or not g.get("pgn"):
            continue
        white, black = g["players"]["white"], g["players"]["black"]
        games.append({
            "site": "lichess", "url": f"https://lichess.org/{g['id']}", "pgn": g["pgn"],
            "white": _lichess_name(white), "black": _lichess_name(black),
            "white_rating": white.get("rating"), "black_rating": black.get("rating"),
            "result": _ending(g["pgn"]), "time_class": g.get("speed"), "rated": g.get("rated"),
            "played_at": (g.get("createdAt") or 0) // 1000,
        })
    return games


SITES = {"chesscom": chesscom_games, "lichess": lichess_games}


def recent_games(site: str, username: str) -> List[dict]:
    if site not in SITES:
        raise ImportProblem("Unknown site.", 400)
    if not USERNAME_RE.match(username or ""):
        raise ImportProblem("That doesn't look like a valid username.", 400)
    key = (site, username.lower())
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    games = SITES[site](username)
    if not games:
        raise ImportProblem("No recent standard games found for that player.", 404)
    _cache[key] = (time.time(), games)
    return games
