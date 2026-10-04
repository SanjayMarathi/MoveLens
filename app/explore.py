"""
The live board: everything the page needs when you play your own moves.

    legal_moves_info(fen)       every legal move from a position, with its SAN and the resulting FEN, so the
                                page can show where a piece may go and apply a move instantly
    explore_move(fen, uci, ..)  judge a move you played: the same labels as the game review
    engine_lines(fen, ..)       the engine's best lines for a position

The engine is passed in as a function `analyse(fen, multipv) -> [EngineLine]`, so these work with Stockfish
in production and with the small stand-in engine in the tests.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .chess_core import START_FEN, Board, parse_sq, sq_name
from .classify import from_side_to_move, move_accuracy
from .openings import OpeningBook, position_key
from .review import PIECE_NAME, analyse_position, coach_text, judge_move, pv_to_san
from .uci import EngineLine

Analyse = Callable[[str, int], List[EngineLine]]


def legal_moves_info(fen: str) -> Dict:
    board = Board(fen)                                   # ValueError for a bad FEN
    legal = board.legal_moves()
    status, winner = board.outcome()
    moves = []
    for m in legal:
        capture = board.squares[m.to] is not None or m.flag == "ep"
        san = board.san(m, legal)
        board._make(m)
        after = board.fen()
        board._unmake()
        moves.append({"uci": m.uci(), "san": san, "fen": after, "capture": capture, "flag": m.flag})
    return {"fen": board.fen(), "turn": board.turn, "check": board.in_check(),
            "status": status, "winner": winner, "moves": moves}


def explore_move(fen: str, uci: str, analyse: Analyse, *, book: Optional[OpeningBook] = None,
                 previous_label: Optional[str] = None, recapture_square: Optional[str] = None) -> Dict:
    """Judge `uci` played from `fen`. Raises ValueError if it isn't a legal move there."""
    before = Board(fen)
    move = next((m for m in before.legal_moves() if m.uci() == uci), None)
    if move is None:
        raise ValueError(f"{uci} is not a legal move in this position.")
    san = before.san(move)
    after = before.copy()
    after.push(move)

    engine = lambda f: analyse(f, 2)                     # noqa: E731 - the review code asks for 2 lines
    a_before = analyse_position(before, engine)
    a_after = analyse_position(after, engine)

    # Book while the game stays inside the opening list (the starting position itself counts as theory).
    from_theory = position_key(before.fen()) == position_key(START_FEN) or bool(book and book.contains(before.fen()))
    is_book = bool(book and from_theory and book.contains(after.fen()))
    facts, label = judge_move(before, after, move, a_before, a_after, is_book=is_book,
                              previous_label=previous_label,
                              recapture_square=parse_sq(recapture_square) if recapture_square else None)

    best_line = a_before.lines[0] if a_before.lines else None
    best_san = pv_to_san(before, [best_line.move], 1)[0] if best_line else None
    sac_piece = PIECE_NAME[before.squares[move.frm].lower()] if label == "brilliant" else None
    opening = book.name(after.fen()) if book and is_book else None
    status, winner = after.outcome()

    reply = None
    if a_after.lines:
        top = a_after.lines[0]
        reply = {"uci": top.move, "san": pv_to_san(after, [top.move], 1)[0]}

    return {
        "san": san, "uci": move.uci(), "from": sq_name(move.frm), "to": sq_name(move.to),
        "color": "white" if before.turn == "w" else "black", "move_number": before.fullmove,
        "fen_before": before.fen(), "fen_after": after.fen(),
        "label": label,
        "eval_before": a_before.score.to_dict(), "eval_after": a_after.score.to_dict(),
        "win_before": round(facts.win_before, 2), "win_after": round(facts.win_after, 2),
        "win_loss": round(facts.loss, 2), "accuracy": round(move_accuracy(facts.loss), 1),
        "best_move": {"san": best_san, "uci": best_line.move} if best_line else None,
        "best_line": pv_to_san(before, best_line.pv) if best_line else [],
        "coach": coach_text(label, san, best_san, facts, a_after.score, before.turn, sac_piece,
                            opening[1] if opening else None),
        "status": status, "winner": winner,
        "reply": reply,
    }


def engine_lines(fen: str, analyse: Analyse, count: int = 3) -> Dict:
    """The engine's best `count` lines from a position, each with its evaluation and moves in SAN."""
    board = Board(fen)
    status, winner = board.outcome()
    if status != "ongoing":
        position = analyse_position(board, lambda f: [])
        return {"fen": board.fen(), "status": status, "winner": winner, "eval": position.score.to_dict(), "lines": []}
    raw = analyse(board.fen(), count)
    if not raw:
        raise RuntimeError("The engine returned no analysis")
    lines = []
    for line in raw:
        score = from_side_to_move(line.cp, line.mate, board.turn)
        san = pv_to_san(board, line.pv, 8)
        lines.append({"uci": line.move, "san": san[0] if san else line.move, "eval": score.to_dict(),
                      "pv": san, "depth": line.depth})
    return {"fen": board.fen(), "status": status, "winner": None, "eval": lines[0]["eval"], "lines": lines}
