"""
Game review pipeline: PGN text in, a fully annotated game out.

    parse PGN -> replay moves -> engine-analyse every position -> label every move -> summarise
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .chess_core import Board, Move, sq_name
from .features import RatingModel, player_features
from .classify import (LABELS, PIECE_VALUE, MoveFacts, Score, classify, find_sacrifice,
                       from_side_to_move, game_accuracy, move_accuracy)
from .openings import OpeningBook
from .pgn import parse_pgn
from .uci import EngineLine

PIECE_NAME = {"p": "pawn", "n": "knight", "b": "bishop", "r": "rook", "q": "queen", "k": "king"}


@dataclass(frozen=True)
class Quality:
    depth: int
    movetime_ms: int


QUALITY = {
    "fast": Quality(depth=12, movetime_ms=150),
    "standard": Quality(depth=16, movetime_ms=400),
    "deep": Quality(depth=20, movetime_ms=1500),
    "max": Quality(depth=24, movetime_ms=3500),
}

# The live board (your own moves, retries, engine lines) answers while you wait, so it searches a bit less.
LIVE_QUALITY = {
    "fast": Quality(depth=12, movetime_ms=200),
    "standard": Quality(depth=16, movetime_ms=450),
    "deep": Quality(depth=18, movetime_ms=800),
    "max": Quality(depth=20, movetime_ms=1400),
}

CLOCK_RE = re.compile(r"\[%clk\s+(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\]")


def comment_clock(comment: str) -> Optional[float]:
    """Seconds left on the clock from a '[%clk 0:09:41.2]' comment, if present."""
    m = CLOCK_RE.search(comment or "")
    return None if not m else int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


@dataclass
class PositionAnalysis:
    score: Score                      # evaluation from White's view (assuming best play)
    lines: List[EngineLine]           # engine's top lines (side-to-move view)


def analyse_position(board: Board, analyse: Callable[[str], List[EngineLine]]) -> PositionAnalysis:
    """Evaluate one position. Game-over positions are scored directly without the engine."""
    status, winner = board.outcome()
    if status == "checkmate":
        return PositionAnalysis(Score(result="1-0" if winner == "w" else "0-1"), [])
    if status != "ongoing":
        return PositionAnalysis(Score(result="1/2-1/2"), [])
    lines = analyse(board.fen())
    if not lines:
        raise RuntimeError("The engine returned no analysis")
    best = lines[0]
    return PositionAnalysis(from_side_to_move(best.cp, best.mate, board.turn), lines)


def pv_to_san(board: Board, pv: List[str], limit: int = 8) -> List[str]:
    """Convert an engine line in UCI ('g1f3 b8c6') to SAN (['Nf3', 'Nc6'])."""
    b = board.copy()
    out = []
    for uci in pv[:limit]:
        legal = b.legal_moves()
        move = next((m for m in legal if m.uci() == uci), None)
        if move is None:
            break
        out.append(b.san(move, legal))
        b.push(move)
    return out


def coach_text(label: str, san: str, best_san: Optional[str], facts: MoveFacts,
               score_after: Score, mover: str, sacrificed_piece: Optional[str], opening: Optional[str]) -> str:
    """A one-line explanation like the 'coach' on chess sites."""
    if label == "book":
        return f"{san} is a book move" + (f" ({opening})." if opening else ".")
    if label == "forced":
        return f"{san} was the only legal move."
    if label == "brilliant":
        piece = f"the {sacrificed_piece}" if sacrificed_piece else "material"
        return f"{san} is brilliant! It gives up {piece}, and it works."
    if label == "great":
        return f"{san} is a great move: the only move that keeps your position this good."
    if label == "best":
        return f"{san} is the best move."
    best = f" The best move was {best_san}." if best_san else ""
    if label in ("excellent", "good"):
        return f"{san} is {label}.{best}"
    consequence = ""
    if score_after.mate is not None and (score_after.mate > 0) != (mover == "w"):
        consequence = f" It allows checkmate in {abs(score_after.mate)}."
    elif facts.win_after < 15 <= facts.win_before:
        consequence = " This should lose the game."
    elif facts.win_before >= 70 and facts.win_after < 60:
        consequence = " It throws away the winning advantage."
    if label == "miss":
        return f"{san} misses the chance to punish your opponent's mistake.{best}"
    article = "an" if label == "inaccuracy" else "a"
    return f"{san} is {article} {label}.{consequence}{best}"


def judge_move(before: Board, after: Board, move: Move, a_before: PositionAnalysis, a_after: PositionAnalysis, *,
               is_book: bool, previous_label: Optional[str],
               recapture_square: Optional[int]) -> Tuple[MoveFacts, str]:
    """Label one move. Shared by the full-game review and by the live board (moves you play yourself).

    `recapture_square` is where the opponent's previous move captured something (None if it didn't)."""
    mover = before.turn
    lines = a_before.lines
    best_line = lines[0] if lines else None

    # Win% for the mover if they had played the best move, and after the move they played.
    win_before = a_before.score.win_for(mover)
    win_after = a_after.score.win_for(mover)
    is_best = best_line is not None and best_line.move == move.uci()
    second_best_win = None
    if len(lines) > 1:
        second = lines[1]
        second_score = from_side_to_move(second.cp, second.mate, before.turn)
        second_best_win = second_score.win_for(mover)
        if second.move == move.uci():
            # The played move was the engine's 2nd choice: use the score from the same search.
            win_after = second_best_win
            if (second.cp, second.mate) == (best_line.cp, best_line.mate):
                is_best = True   # equally good as the top move

    captured = before.squares[move.to]
    captured_value = PIECE_VALUE[captured.lower()] if captured else (1 if move.flag == "ep" else 0)
    facts = MoveFacts(
        win_before=win_before, win_after=win_after, is_best=is_best,
        second_best_win=second_best_win, legal_move_count=len(before.legal_moves()),
        in_check=before.in_check(), is_book=is_book,
        is_recapture=bool(captured and recapture_square == move.to),
        sacrifice=find_sacrifice(after, mover, captured_value), is_promotion=move.promo is not None,
        previous_label=previous_label,
        delivers_mate=a_after.score.result in ("1-0", "0-1"),
    )
    return facts, classify(facts)


def review_game(pgn_text: str, analyse: Callable[[str], List[EngineLine]],
                book: Optional[OpeningBook] = None,
                rating_model: Optional[RatingModel] = None,
                progress: Optional[Callable[[int, int], None]] = None) -> Dict:
    """Run a full review.

    `analyse(fen)` must return the engine's top lines (MultiPV 2) for a position, so the pipeline
    works with Stockfish in production and with a small stand-in engine in tests."""
    game = parse_pgn(pgn_text)

    # 1. Replay the game, keeping a board for every position (n moves -> n+1 positions).
    boards = [Board(game.start_fen)]
    for move in game.moves:
        b = boards[-1].copy()
        # carry over repetition history so threefold draws are detected correctly
        b._positions = list(boards[-1]._positions)
        b.push(move)
        boards.append(b)

    # 2. Analyse every position with the engine.
    total = len(boards)
    analyses: List[PositionAnalysis] = []
    for i, board in enumerate(boards):
        analyses.append(analyse_position(board, analyse))
        if progress:
            progress(i + 1, total)

    # 3. Label every move.
    moves_out = []
    labels: List[str] = []
    still_in_book = True
    opening = None
    for i, move in enumerate(game.moves):
        before, after = boards[i], boards[i + 1]
        mover = before.turn
        a_before, a_after = analyses[i], analyses[i + 1]
        best_line = a_before.lines[0] if a_before.lines else None

        # Opening book
        is_book = False
        if still_in_book and book is not None and book.contains(after.fen()):
            is_book = True
            name = book.name(after.fen())
            if name:
                opening = name
        else:
            still_in_book = False

        prev = game.moves[i - 1] if i > 0 else None
        recapture_square = prev.to if prev and boards[i - 1].squares[prev.to] is not None else None
        facts, label = judge_move(before, after, move, a_before, a_after, is_book=is_book,
                                  previous_label=labels[-1] if labels else None,
                                  recapture_square=recapture_square)
        labels.append(label)
        win_before, win_after = facts.win_before, facts.win_after

        best_san = pv_to_san(before, [best_line.move], 1)[0] if best_line else None
        sac_piece = None
        if label == "brilliant":
            sac_piece = PIECE_NAME[before.squares[move.frm].lower()]
        moves_out.append({
            "ply": i + 1,
            "move_number": before.fullmove,
            "color": "white" if mover == "w" else "black",
            "san": game.sans[i],
            "uci": move.uci(),
            "from": sq_name(move.frm),
            "to": sq_name(move.to),
            "fen_before": before.fen(),
            "fen_after": after.fen(),
            "label": label,
            "eval_after": a_after.score.to_dict(),
            "win_before": round(win_before, 2),
            "win_after": round(win_after, 2),
            "win_loss": round(facts.loss, 2),
            "accuracy": round(move_accuracy(facts.loss), 1),
            "best_move": {"san": best_san, "uci": best_line.move} if best_line else None,
            "best_line": pv_to_san(before, best_line.pv) if best_line else [],
            "coach": coach_text(label, game.sans[i], best_san, facts, a_after.score, mover,
                                sac_piece, opening[1] if opening else None),
            "clock": comment_clock(game.comments[i]),       # seconds left after this move, if the PGN has clocks
        })

    # 4. Summaries per player.
    white_wins = [a.score.win_white() for a in analyses]
    move_accs = [m["accuracy"] for m in moves_out]
    movers = [b.turn for b in boards[:-1]]
    players = {}
    for color, key in (("w", "white"), ("b", "black")):
        counts = {label: 0 for label in LABELS}
        for m in moves_out:
            if m["color"] == key:
                counts[m["label"]] += 1
        players[key] = {
            "name": game.headers.get("White" if color == "w" else "Black", key.capitalize()),
            "rating": game.headers.get("WhiteElo" if color == "w" else "BlackElo"),
            "accuracy": game_accuracy(white_wins, move_accs, movers, color),
            "counts": counts,
            "estimated_rating": None,
        }
        if rating_model is not None and rating_model.available:
            losses = [m["win_loss"] for m in moves_out
                      if m["color"] == key and m["label"] not in ("book", "forced")]
            players[key]["estimated_rating"] = rating_model.predict(
                player_features(losses, game.headers.get("TimeControl")))

    return {
        "headers": game.headers,
        "time_control": game.headers.get("TimeControl"),
        "start_fen": game.start_fen,
        "start_eval": analyses[0].score.to_dict(),
        "opening": {"eco": opening[0], "name": opening[1]} if opening else None,
        "result": game.headers.get("Result", "*"),
        "players": players,
        "moves": moves_out,
    }
