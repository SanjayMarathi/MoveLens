"""The live board's building blocks, tested without an engine process."""
import pytest

from app.explore import engine_lines, explore_move, legal_moves_info
from app.openings import OpeningBook
from app.review import comment_clock
from tests.fake_engine import analyse

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.fixture(scope="module")
def book():
    return OpeningBook().load()


def test_comment_clock_reads_chess_com_and_lichess_styles():
    assert comment_clock("{[%clk 0:09:59.9]}") == pytest.approx(599.9)
    assert comment_clock("[%eval 0.3] [%clk 1:02:03]") == 3723
    assert comment_clock("no clock here") is None and comment_clock("") is None


def test_legal_moves_include_castling_and_all_four_promotions():
    castle = legal_moves_info("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    ucis = {m["uci"] for m in castle["moves"]}
    assert {"e1g1", "e1c1"} <= ucis                                  # both castling moves, as king moves
    assert next(m for m in castle["moves"] if m["uci"] == "e1g1")["san"] == "O-O"

    promo = legal_moves_info("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert {m["uci"] for m in promo["moves"] if m["uci"].startswith("a7a8")} == {"a7a8q", "a7a8r", "a7a8b", "a7a8n"}


def test_legal_moves_report_check_capture_and_game_over():
    check = legal_moves_info("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
    assert check["check"] is True
    assert next(m for m in check["moves"] if m["uci"] == "e1e2")["capture"] is True
    mate = legal_moves_info("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert mate["status"] == "checkmate" and mate["moves"] == [] and mate["winner"] == "b"


def test_explore_move_matches_review_labels(book):
    # 3...Nf6?? allows Qxf7#, exactly like in the full-game review
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    r = explore_move(fen, "g8f6", analyse, book=book)
    assert r["label"] == "blunder" and "checkmate in 1" in r["coach"]
    assert r["eval_before"]["text"] != r["eval_after"]["text"] and r["status"] == "ongoing"
    assert r["reply"]["san"] == "Qxf7#"


def test_explore_move_book_move_and_game_over(book):
    r = explore_move(START, "e2e4", analyse, book=book)
    assert r["label"] == "book" and r["san"] == "e4" and r["move_number"] == 1 and r["color"] == "white"
    mate = explore_move("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 3 3", "h5f7", analyse)
    assert mate["status"] == "checkmate" and mate["winner"] == "w" and mate["reply"] is None


def test_explore_rejects_illegal_moves():
    with pytest.raises(ValueError):
        explore_move(START, "e2e5", analyse)


def test_engine_lines_have_readable_moves():
    data = engine_lines(START, analyse, 2)
    assert data["status"] == "ongoing" and len(data["lines"]) == 2
    assert all(l["san"] and l["pv"][0] == l["san"] for l in data["lines"])
    over = engine_lines("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3", analyse, 3)
    assert over["lines"] == [] and over["status"] == "checkmate"
