"""Importer tests: the network is replaced by canned responses."""
import json

import pytest

from app import importer
from app.importer import ImportProblem, chesscom_games, lichess_games, recent_games

PGN = '[Event "Live Chess"]\n[White "alice"]\n[Black "bob"]\n[Result "0-1"]\n\n1. e4 e5 0-1'


def test_chesscom_games_are_parsed_sorted_and_filtered():
    archive = "https://api.chess.com/pub/player/alice/games/2026/10"

    def fetch(url, accept=None):
        if url.endswith("/games/archives"):
            return json.dumps({"archives": [archive]}).encode()
        assert url == archive
        return json.dumps({"games": [
            {"url": "u1", "pgn": PGN, "rules": "chess", "time_class": "rapid", "rated": True, "end_time": 100,
             "white": {"username": "alice", "rating": 800}, "black": {"username": "bob", "rating": 790}},
            {"url": "u2", "pgn": PGN, "rules": "chess960", "end_time": 300,
             "white": {"username": "alice"}, "black": {"username": "bob"}},
            {"url": "u3", "pgn": PGN, "rules": "chess", "end_time": 200,
             "white": {"username": "bob", "rating": 1}, "black": {"username": "alice", "rating": 2}},
        ]}).encode()

    games = chesscom_games("alice", fetch)
    assert [g["url"] for g in games] == ["u3", "u1"]               # chess960 dropped, newest first
    assert games[1]["white_rating"] == 800 and games[1]["result"] == "0-1" and games[1]["time_class"] == "rapid"


def test_lichess_games_are_parsed():
    ndjson = "\n".join(json.dumps(g) for g in [
        {"id": "abc", "variant": "standard", "speed": "blitz", "rated": True, "createdAt": 5000, "pgn": PGN,
         "players": {"white": {"user": {"name": "alice"}, "rating": 1500}, "black": {"aiLevel": 3}}},
        {"id": "xyz", "variant": "atomic", "pgn": PGN, "players": {"white": {}, "black": {}}},
    ]).encode()
    games = lichess_games("alice", lambda url, accept=None: ndjson)
    assert len(games) == 1 and games[0]["white"] == "alice" and games[0]["black"] == "Stockfish"
    assert games[0]["url"] == "https://lichess.org/abc" and games[0]["played_at"] == 5


@pytest.mark.parametrize("site,user,status", [("nope", "alice", 400), ("chesscom", "bad name!", 400), ("lichess", "", 400)])
def test_bad_requests_are_rejected_before_any_network_call(site, user, status):
    with pytest.raises(ImportProblem) as e:
        recent_games(site, user)
    assert e.value.status == status


def test_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setitem(importer.SITES, "chesscom", lambda u: calls.append(u) or [{"pgn": PGN}])
    importer._cache.clear()
    recent_games("chesscom", "Cached_User")
    recent_games("chesscom", "cached_user")
    assert len(calls) == 1
