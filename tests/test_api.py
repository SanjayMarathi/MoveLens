"""API tests. Uses the stand-in engine so no Stockfish install is needed."""
import os
import stat
import sys
import time
from collections import OrderedDict
from pathlib import Path

import pytest

# Point the server at a tiny launcher script that starts tests/fake_engine.py (a shell script, or a .bat on Windows).
_engine_py = Path(__file__).with_name("fake_engine.py")
if os.name == "nt":
    _wrapper = Path(__file__).with_name("_fake_engine.bat")
    _wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{_engine_py}"\r\n')
else:
    _wrapper = Path(__file__).with_name("_fake_engine.sh")
    _wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{_engine_py}"\n')
    _wrapper.chmod(_wrapper.stat().st_mode | stat.S_IEXEC)
os.environ["STOCKFISH_PATH"] = str(_wrapper)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as server  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def wait_for(job_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/reviews/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    pytest.fail("review timed out")


def test_homepage_and_health():
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["engine_found"]


def test_piece_sets_are_served():
    res = client.get("/static/pieces/cburnett/wK.svg")
    assert res.status_code == 200 and "svg" in res.headers["content-type"]


def test_page_is_marked_so_the_service_worker_can_tell_it_from_a_hosts_waking_page():
    assert client.get("/").headers["x-movelens"] == "1"
    health = client.get("/api/health").json()
    assert health["cpus"] >= 1 and health["max_queued"] >= 1


def test_waiting_reviews_are_told_how_many_are_ahead(monkeypatch):
    now = time.time()
    fake = OrderedDict()
    for i, status in enumerate(["running", "queued", "queued"]):
        job = server.Job("x", "fast", 3)
        job.id, job.status, job.created = f"q{i}", status, now + i
        fake[job.id] = job
    monkeypatch.setattr(server, "jobs", fake)
    monkeypatch.setattr(server, "ENGINE_WORKERS", 1)
    assert client.get("/api/reviews/q2").json()["ahead"] == 2
    assert client.get("/api/reviews/q1").json()["ahead"] == 1
    assert "ahead" not in client.get("/api/reviews/q0").json()                 # already running
    monkeypatch.setattr(server, "ENGINE_WORKERS", 2)                            # two engines: one fewer to wait for
    assert client.get("/api/reviews/q2").json()["ahead"] == 1


def test_service_worker_is_versioned_and_lists_the_app_files():
    res = client.get("/sw.js")
    assert res.status_code == 200 and "javascript" in res.headers["content-type"]
    assert res.headers["service-worker-allowed"] == "/" and "no-cache" in res.headers["cache-control"]
    body = res.text
    assert "__VERSION__" not in body and "__PRECACHE__" not in body
    for needed in ("/static/js/main.js", "/static/css/app.css", "/static/pieces/cburnett/wK.svg", "/static/data/opera.json", '"/"'):
        assert needed in body
    assert client.get("/sw.js").text == body                   # same files -> same version


def test_manifest_and_icons_are_served():
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200 and res.json()["start_url"] == "/"
    for icon in res.json()["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_review_job_lifecycle():
    res = client.post("/api/reviews", json={"pgn": "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#", "quality": "fast"})
    assert res.status_code == 200
    job = wait_for(res.json()["id"])
    assert job["status"] == "done", job["error"]
    assert job["progress"] == {"done": 8, "total": 8}
    assert job["result"]["moves"][5]["label"] == "blunder"
    assert job["result"]["quality"] == "fast"


def test_bad_pgn_is_rejected_immediately():
    res = client.post("/api/reviews", json={"pgn": "1. e4 e5 2. Ke3"})
    assert res.status_code == 400 and "Ke3" in res.json()["detail"]


def test_quality_is_capped_by_server_setting(monkeypatch):
    monkeypatch.setattr(server, "MAX_QUALITY", "standard")
    res = client.post("/api/reviews", json={"pgn": "1. e4", "quality": "deep"})
    assert res.json()["quality"] == "standard"


def test_unknown_review():
    assert client.get("/api/reviews/nope").status_code == 404


# ---------------------------------------------------------------- live board
def test_legal_moves_endpoint():
    data = client.post("/api/legal", json={"fen": START}).json()
    assert data["turn"] == "w" and data["status"] == "ongoing" and len(data["moves"]) == 20
    e4 = next(m for m in data["moves"] if m["uci"] == "e2e4")
    assert e4["san"] == "e4" and e4["fen"].startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b")
    assert client.post("/api/legal", json={"fen": "nonsense"}).status_code == 400


def test_explore_judges_a_move_and_rejects_bad_ones():
    ok = client.post("/api/explore", json={"fen": START, "uci": "e2e4", "quality": "fast"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["san"] == "e4" and body["label"] in ("book", "best", "excellent", "good")
    assert body["fen_after"].startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b")
    assert set(["eval_before", "eval_after", "coach", "reply", "best_move"]) <= set(body)
    assert client.post("/api/explore", json={"fen": START, "uci": "e2e5"}).status_code == 400
    assert client.post("/api/explore", json={"fen": START, "uci": "zz"}).status_code == 422


def test_explore_flags_walking_into_mate():
    # 1.e4 e5 2.Qh5 Nc6 3.Bc4 and now ...Nf6?? allows Qxf7#
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    body = client.post("/api/explore", json={"fen": fen, "uci": "g8f6", "quality": "fast"}).json()
    assert body["label"] == "blunder" and "checkmate in 1" in body["coach"]
    assert body["best_move"]["san"] in ("g6", "Qe7", "Qf6", "Nh6")


def test_engine_lines_endpoint():
    data = client.post("/api/analyse", json={"fen": START, "count": 3, "quality": "fast"}).json()
    assert data["status"] == "ongoing" and 1 <= len(data["lines"]) <= 3
    assert data["lines"][0]["san"] and "text" in data["lines"][0]["eval"]
