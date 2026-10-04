import pytest

from app.pgn import comment_eval, parse_pgn

CHESS_COM_STYLE = """[Event "Live Chess"]
[Site "Chess.com"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[WhiteElo "1450"]
[BlackElo "1432"]
[TimeControl "600"]

1. e4 {[%clk 0:09:58.1]} 1... e5 {[%clk 0:09:57]} 2. Nf3 {[%clk 0:09:55]} 2... Nc6
3. Bc4 $1 (3. Bb5 a6 (3... Nf6) 4. Ba4) 3... Nf6?! 4. Ng5 d5 5. exd5 Na5 6. Bb5+ c6
7. dxc6 bxc6 8. Qf3!? Rb8 9. Bxc6+ Nxc6 10. Qxc6+ Bd7 11. Qa6 1-0
"""


def test_reads_headers_moves_and_ignores_clocks_variations_glyphs():
    g = parse_pgn(CHESS_COM_STYLE)
    assert g.headers["White"] == "alice" and g.headers["WhiteElo"] == "1450"
    assert len(g.moves) == 21
    assert g.sans[:6] == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"]
    assert g.sans[-1] == "Qa6"
    assert "%clk" in g.comments[0]


def test_plain_move_list_with_glued_numbers_and_zero_castling():
    g = parse_pgn("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.0-0 Nf6")
    assert g.sans[-2:] == ["O-O", "Nf6"]


def test_promotion_without_equals_sign():
    g = parse_pgn('[FEN "8/4P1k1/8/8/8/8/8/4K3 w - - 0 1"]\n\n1. e8Q')
    assert g.sans == ["e8=Q"]


def test_illegal_move_gives_helpful_error():
    with pytest.raises(ValueError, match="Move 2 for White"):
        parse_pgn("1. e4 e5 2. Ke3")


def test_only_first_game_is_used():
    two = '[White "a"]\n\n1. e4 e5 1-0\n\n[White "b"]\n\n1. d4 d5 0-1\n'
    g = parse_pgn(two)
    assert g.headers["White"] == "a" and g.sans == ["e4", "e5"]


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        parse_pgn("   ")
    with pytest.raises(ValueError):
        parse_pgn('[White "x"]\n')


def test_lichess_eval_comments():
    assert comment_eval("[%eval 0.31] [%clk 0:05:00]") == "0.31"
    assert comment_eval("[%eval #-3]") == "#-3"
    assert comment_eval("good move") is None
