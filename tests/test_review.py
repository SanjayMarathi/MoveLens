"""End-to-end review tests using the stand-in engine (tests/fake_engine.py) instead of Stockfish."""
import sys
from pathlib import Path

import pytest

from app.openings import OpeningBook
from app.review import review_game
from app.uci import UciEngine, parse_info
from tests.fake_engine import analyse

FAKE_ENGINE = [sys.executable, str(Path(__file__).with_name("fake_engine.py"))]


@pytest.fixture(scope="module")
def book():
    return OpeningBook().load()


def test_scholars_mate_review(book):
    r = review_game("1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0", analyse, book)
    moves = r["moves"]
    assert [m["san"] for m in moves] == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    assert moves[0]["label"] == "book"
    assert moves[5]["label"] == "blunder"                 # 3...Nf6?? allows mate
    assert "checkmate in 1" in moves[5]["coach"]
    assert moves[5]["best_move"]["san"] in ("g6", "Qe7", "Qf6", "Nh6")
    assert moves[6]["label"] == "best" and moves[6]["eval_after"]["text"] == "1-0"
    assert r["players"]["black"]["counts"]["blunder"] == 1
    assert r["players"]["white"]["accuracy"] > r["players"]["black"]["accuracy"]


def test_progress_callback_and_opening(book):
    calls = []
    r = review_game("1. e4 e5 2. Nf3 Nc6 3. Bb5", analyse, book, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (6, 6)
    assert r["opening"]["name"] == "Ruy Lopez"


def test_review_through_real_uci_protocol(book):
    with UciEngine(FAKE_ENGINE) as engine:
        engine.new_game()
        r = review_game("1. d4 d5 2. c4", lambda fen: engine.analyse(fen, depth=2, multipv=2), book)
    assert len(r["moves"]) == 3 and r["moves"][2]["label"] == "book"


def test_parse_info_lines():
    idx, line = parse_info("info depth 20 seldepth 30 multipv 2 score cp -35 nodes 1 nps 2 pv e7e5 g1f3")
    assert idx == 2 and line.cp == -35 and line.pv == ["e7e5", "g1f3"] and line.move == "e7e5"
    _, mate = parse_info("info depth 9 multipv 1 score mate -3 pv h7h6")
    assert mate.mate == -3
    assert parse_info("info depth 5 multipv 1 score cp 10 lowerbound pv e2e4") is None
    assert parse_info("info string NNUE enabled") is None
