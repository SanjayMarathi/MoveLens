"""
How moves get their labels (Brilliant, Great, Best, ... Blunder).

There is no trained neural network deciding "brilliant". The idea used by review tools is:

1. Ask a strong engine (Stockfish) how good the position is before and after each move.
2. Convert the engine score (centipawns) into WIN PERCENTAGE, a 0-100 chance of winning.
   +1 pawn is huge between beginners in an equal position but irrelevant when you're already
   up a queen. Win% captures that: the curve is steep near 0 and flat at the extremes.
3. A move's quality = how much win% it threw away compared to the engine's best move.
4. Special labels (Brilliant, Great, Miss, Book, Forced) add simple chess rules on top.

The thresholds below are tuned to feel like the big chess sites; they are approximations,
and changing them is the easiest way to experiment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import pstdev
from typing import List, Optional, Sequence

from .chess_core import Board, Move

# --------------------------------------------------------------------------- win %
WIN_SLOPE = 0.00368208   # Lichess's fitted constant: maps centipawns to win chance


def win_percent_cp(cp: float) -> float:
    """Centipawns (from a player's point of view) -> that player's winning chance, 0..100."""
    return 50 + 50 * (2 / (1 + math.exp(-WIN_SLOPE * cp)) - 1)


@dataclass
class Score:
    """An engine evaluation from WHITE's point of view."""
    cp: Optional[int] = None
    mate: Optional[int] = None         # +N: White mates in N, -N: Black mates in N
    result: Optional[str] = None       # set when the game is over on the board: "1-0", "0-1", "1/2-1/2"

    def win_white(self) -> float:
        if self.result is not None:
            return {"1-0": 100.0, "0-1": 0.0}.get(self.result, 50.0)
        if self.mate is not None:
            return 100.0 if self.mate > 0 else 0.0
        return win_percent_cp(self.cp or 0)

    def win_for(self, color: str) -> float:
        w = self.win_white()
        return w if color == "w" else 100.0 - w

    def text(self) -> str:
        """Human-readable evaluation: '+1.25', '-0.40', 'M3', '-M2', '1-0'."""
        if self.result is not None:
            return "½-½" if self.result == "1/2-1/2" else self.result
        if self.mate is not None:
            return ("M" if self.mate > 0 else "-M") + str(abs(self.mate))
        return f"{(self.cp or 0) / 100:+.2f}"

    def to_dict(self) -> dict:
        return {"cp": self.cp, "mate": self.mate, "result": self.result, "text": self.text(),
                "win_white": round(self.win_white(), 2)}


def from_side_to_move(cp: Optional[int], mate: Optional[int], turn: str) -> Score:
    """Engines score from the side to move's view; flip it to White's view."""
    sign = 1 if turn == "w" else -1
    return Score(cp=None if cp is None else sign * cp, mate=None if mate is None else sign * mate)


# --------------------------------------------------------------------------- accuracy
def move_accuracy(win_loss: float) -> float:
    """Lichess's accuracy curve: 0 win% lost -> 100, 10 lost -> ~65, 30 lost -> ~25."""
    acc = 103.1668 * math.exp(-0.04354 * max(0.0, win_loss)) - 3.1669
    return max(0.0, min(100.0, acc))


def game_accuracy(white_wins: Sequence[float], move_accuracies: Sequence[float],
                  movers: Sequence[str], color: str) -> Optional[float]:
    """Overall accuracy for one player (the method Lichess uses).

    A plain average would let 30 easy moves hide one game-losing blunder, so we average two things:
    * a weighted mean, where moves in sharp moments (where win% was swinging) count more;
    * a harmonic mean, which is pulled down hard by any very bad move.
    `white_wins` has one entry per position (len = moves + 1)."""
    n = len(move_accuracies)
    if n == 0:
        return None
    window = max(2, min(8, n // 10))
    weights = []
    for i in range(n):
        start = max(0, min(i - window // 2, len(white_wins) - window))
        chunk = white_wins[start:start + window]
        weights.append(max(0.5, min(12.0, pstdev(chunk))))

    picks = [(a, w) for a, w, c in zip(move_accuracies, weights, movers) if c == color]
    if not picks:
        return None
    weighted = sum(a * w for a, w in picks) / sum(w for _, w in picks)
    harmonic = len(picks) / sum(1 / max(a, 1.0) for a, _ in picks)
    return round((weighted + harmonic) / 2, 1)


# --------------------------------------------------------------------------- labels
LABELS = ["brilliant", "great", "best", "excellent", "good", "book", "forced",
          "inaccuracy", "mistake", "miss", "blunder"]

# Win% lost compared with the best move (same scale as "expected points" x 100).
EXCELLENT_MAX = 2.0
GOOD_MAX = 5.0
INACCURACY_MAX = 10.0
MISTAKE_MAX = 20.0          # more than this is a blunder

GREAT_GAP = 10.0            # "only move": the 2nd best move is at least this much worse
BRILLIANT_MIN_SACRIFICE = 2 # pawns of material deliberately left to be taken
PIECE_VALUE = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 0}


def find_sacrifice(board_after: Board, mover: str, captured_value: int) -> int:
    """How much material (in pawns) did the mover leave for the opponent to take?

    `board_after` is the position after the move (opponent to move). For each of the mover's
    pieces (pawns don't count: that's a gambit, not a sacrifice) that the opponent can legally
    capture, the material at risk is the piece's value if it's undefended, or
    (piece - cheapest capturer) if it's defended. Whatever the move itself captured is
    subtracted, so a fair trade (e.g. QxQ) is not a sacrifice."""
    squares = board_after.squares
    replies = board_after.legal_moves()
    worst = 0
    for sq, piece in enumerate(squares):
        if piece is None or piece in "PpKk" or (piece.isupper() != (mover == "w")):
            continue
        capturers = [PIECE_VALUE[squares[m.frm].lower()] for m in replies if m.to == sq]
        if not capturers:
            continue
        value = PIECE_VALUE[piece.lower()]
        defended = board_after.is_attacked(sq, mover)
        at_risk = value - min(capturers) if defended else value
        worst = max(worst, at_risk)
    return worst - captured_value


@dataclass
class MoveFacts:
    """Everything the classifier needs to know about one move."""
    win_before: float                 # mover's win% before the move (if they play the best move)
    win_after: float                  # mover's win% after the move actually played
    is_best: bool                     # played the engine's top move
    second_best_win: Optional[float]  # mover's win% after the engine's 2nd choice (None if there is none)
    legal_move_count: int
    in_check: bool
    is_book: bool
    is_recapture: bool                # captured on the square where the opponent just captured
    sacrifice: int                    # result of find_sacrifice()
    is_promotion: bool
    previous_label: Optional[str]     # the opponent's previous move label
    delivers_mate: bool = False       # the move checkmates

    @property
    def loss(self) -> float:
        return 0.0 if self.is_best else max(0.0, self.win_before - self.win_after)


def classify(f: MoveFacts) -> str:
    if f.is_book:
        return "book"
    if f.legal_move_count == 1:
        return "forced"

    loss = f.loss
    if f.is_best or loss < 1.0:
        # Brilliant: a (near) best move that sacrifices material, when you weren't already
        # completely winning and you aren't worse afterwards.
        if (f.sacrifice >= BRILLIANT_MIN_SACRIFICE and not f.is_promotion
                and f.win_before < 97 and f.win_after >= 48):
            return "brilliant"
        if f.delivers_mate:
            return "best"
        # Great: the only move. Every alternative is much worse, and it's not an obvious
        # recapture or a forced reply to check.
        if (f.is_best and f.second_best_win is not None
                and f.win_before - f.second_best_win >= GREAT_GAP
                and f.second_best_win < 90 and not f.is_recapture and not f.in_check):
            return "great"
        if f.is_best:
            return "best"

    if loss < EXCELLENT_MAX:
        return "excellent"
    if loss < GOOD_MAX:
        return "good"

    # Miss: the opponent just made a mistake and you didn't take advantage of it.
    if f.previous_label in ("mistake", "blunder") and loss >= INACCURACY_MAX and f.win_after > 30:
        return "miss"
    if loss < INACCURACY_MAX:
        return "inaccuracy"
    if loss < MISTAKE_MAX:
        return "mistake"
    return "blunder"
