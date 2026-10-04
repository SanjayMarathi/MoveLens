import pytest

from app.chess_core import START_FEN, Board, parse_sq, perft


# Known-correct perft node counts (https://www.chessprogramming.org/Perft_Results).
# Matching these proves the move generator handles every rule exactly right.
@pytest.mark.parametrize("fen, expected", [
    (START_FEN, [20, 400, 8902]),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039]),   # "Kiwipete"
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812]),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467]),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486]),
])
def test_perft(fen, expected):
    board = Board(fen)
    for depth, count in enumerate(expected, start=1):
        assert perft(board, depth) == count
    assert board.fen() == fen  # make/unmake restored everything


def play(board, *sans):
    for san in sans:
        legal = board.legal_moves()
        move = next(m for m in legal if board.san(m, legal).rstrip("+#") == san)
        board.push(move)


def test_fools_mate_is_checkmate():
    b = Board()
    play(b, "f3", "e5", "g4", "Qh4")
    assert b.outcome() == ("checkmate", "b")


def test_stalemate():
    assert Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").outcome() == ("stalemate", None)


def test_insufficient_material():
    assert Board("8/8/8/4k3/8/8/8/4K3 w - - 0 1").outcome()[0] == "insufficient_material"
    assert Board("8/8/8/4k3/8/8/8/2B1K3 w - - 0 1").outcome()[0] == "insufficient_material"
    assert Board("8/8/8/4k3/8/8/8/R3K3 w - - 0 1").outcome()[0] == "ongoing"


def test_threefold_repetition():
    b = Board()
    play(b, "Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8")
    assert b.outcome()[0] == "threefold_repetition"


def test_fifty_move_rule():
    assert Board("8/8/8/4k3/8/8/8/R3K3 w - - 100 80").outcome()[0] == "fifty_move"


def test_castling_and_rights():
    b = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    play(b, "O-O")
    assert b.squares[parse_sq("g1")] == "K" and b.squares[parse_sq("f1")] == "R"
    assert b.castling == "kq"
    play(b, "O-O-O")
    assert b.squares[parse_sq("c8")] == "k" and b.squares[parse_sq("d8")] == "r"


def test_cannot_castle_through_check():
    b = Board("4k3/8/8/8/8/8/5r2/R3K2R w KQ - 0 1")  # rook on f2 attacks f1
    sans = {b.san(m) for m in b.legal_moves()}
    assert "O-O" not in sans and "O-O-O" in sans


def test_en_passant():
    b = Board()
    play(b, "e4", "a6", "e5", "d5")
    legal = b.legal_moves()
    ep = [m for m in legal if m.flag == "ep"]
    assert len(ep) == 1 and b.san(ep[0], legal) == "exd6"
    b.push(ep[0])
    assert b.squares[parse_sq("d5")] is None
    b.pop()
    assert b.squares[parse_sq("d5")] == "p"


def test_promotion_and_san():
    b = Board("8/4P1k1/8/8/8/8/8/4K3 w - - 0 1")
    move = b.find_move("e7", "e8", "q")
    assert b.san(move) == "e8=Q"
    b.push(move)
    assert b.squares[parse_sq("e8")] == "Q"
    assert len([m for m in Board("8/4P1k1/8/8/8/8/8/4K3 w - - 0 1").legal_moves() if m.promo]) == 4


def test_san_disambiguation():
    b = Board("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
    assert b.san(b.find_move("b1", "d2")) == "Nbd2"


def test_invalid_fen_rejected():
    with pytest.raises(ValueError):
        Board("this is not a fen")
    with pytest.raises(ValueError):
        Board("8/8/8/8/8/8/8/8 w - - 0 1")  # no kings
