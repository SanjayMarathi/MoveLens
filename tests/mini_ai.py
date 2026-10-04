"""
Chess AI: negamax search with alpha-beta pruning, quiescence search,
MVV-LVA move ordering and piece-square-table evaluation.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional

from app.chess_core import WHITE, Board, Move

MATE = 100_000
PIECE_VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}

# Piece-square tables, written from White's point of view with rank 8 at the top.
# Values are a bonus (centipawns) for a piece standing on that square.
PST = {
    "p": [
         0,  0,  0,  0,  0,  0,  0,  0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
         5,  5, 10, 25, 25, 10,  5,  5,
         0,  0,  0, 20, 20,  0,  0,  0,
         5, -5,-10,  0,  0,-10, -5,  5,
         5, 10, 10,-20,-20, 10, 10,  5,
         0,  0,  0,  0,  0,  0,  0,  0],
    "n": [
        -50,-40,-30,-30,-30,-30,-40,-50,
        -40,-20,  0,  0,  0,  0,-20,-40,
        -30,  0, 10, 15, 15, 10,  0,-30,
        -30,  5, 15, 20, 20, 15,  5,-30,
        -30,  0, 15, 20, 20, 15,  0,-30,
        -30,  5, 10, 15, 15, 10,  5,-30,
        -40,-20,  0,  5,  5,  0,-20,-40,
        -50,-40,-30,-30,-30,-30,-40,-50],
    "b": [
        -20,-10,-10,-10,-10,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0,  5, 10, 10,  5,  0,-10,
        -10,  5,  5, 10, 10,  5,  5,-10,
        -10,  0, 10, 10, 10, 10,  0,-10,
        -10, 10, 10, 10, 10, 10, 10,-10,
        -10,  5,  0,  0,  0,  0,  5,-10,
        -20,-10,-10,-10,-10,-10,-10,-20],
    "r": [
          0,  0,  0,  0,  0,  0,  0,  0,
          5, 10, 10, 10, 10, 10, 10,  5,
         -5,  0,  0,  0,  0,  0,  0, -5,
         -5,  0,  0,  0,  0,  0,  0, -5,
         -5,  0,  0,  0,  0,  0,  0, -5,
         -5,  0,  0,  0,  0,  0,  0, -5,
         -5,  0,  0,  0,  0,  0,  0, -5,
          0,  0,  0,  5,  5,  0,  0,  0],
    "q": [
        -20,-10,-10, -5, -5,-10,-10,-20,
        -10,  0,  0,  0,  0,  0,  0,-10,
        -10,  0,  5,  5,  5,  5,  0,-10,
         -5,  0,  5,  5,  5,  5,  0, -5,
          0,  0,  5,  5,  5,  5,  0, -5,
        -10,  5,  5,  5,  5,  5,  0,-10,
        -10,  0,  5,  0,  0,  0,  0,-10,
        -20,-10,-10, -5, -5,-10,-10,-20],
    "k": [   # middlegame: stay safe behind pawns
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -20,-30,-30,-40,-40,-30,-30,-20,
        -10,-20,-20,-20,-20,-20,-20,-10,
         20, 20,  0,  0,  0,  0, 20, 20,
         20, 30, 10,  0,  0, 10, 30, 20],
    "k_end": [  # endgame: king becomes an active piece
        -50,-40,-30,-20,-20,-30,-40,-50,
        -30,-20,-10,  0,  0,-10,-20,-30,
        -30,-10, 20, 30, 30, 20,-10,-30,
        -30,-10, 30, 40, 40, 30,-10,-30,
        -30,-10, 30, 40, 40, 30,-10,-30,
        -30,-10, 20, 30, 30, 20,-10,-30,
        -30,-30,  0,  0,  0,  0,-30,-30,
        -50,-30,-30,-30,-30,-30,-30,-50],
}


def evaluate(board: Board) -> int:
    """Static evaluation in centipawns from the side-to-move's point of view."""
    squares = board.squares
    non_pawn_material = sum(PIECE_VALUES[p.lower()] for p in squares if p and p.lower() in "nbrq")
    endgame = non_pawn_material <= 1300
    score = 0
    for sq, p in enumerate(squares):
        if p is None:
            continue
        kind = p.lower()
        table = PST["k_end"] if (kind == "k" and endgame) else PST[kind]
        if p.isupper():
            score += PIECE_VALUES[kind] + table[(7 - sq // 8) * 8 + sq % 8]
        else:
            score -= PIECE_VALUES[kind] + table[sq]
    return score if board.turn == WHITE else -score


@dataclass
class SearchResult:
    move: Optional[Move]
    score: int
    nodes: int
    seconds: float


class ChessAI:
    def __init__(self, depth: int = 2, randomness: bool = True, max_quiescence: int = 6):
        self.depth = max(1, depth)
        self.randomness = randomness
        self.max_quiescence = max_quiescence
        self.nodes = 0

    # ---------------------------------------------------------------- public
    def choose_move(self, board: Board) -> SearchResult:
        start = time.perf_counter()
        self.nodes = 0
        moves = board.legal_moves()
        if not moves:
            return SearchResult(None, 0, 0, 0.0)
        if self.randomness:
            random.shuffle(moves)  # vary play between games when moves score equally
        moves = self._order(board, moves)

        best_move, alpha, beta = moves[0], -MATE - 1, MATE + 1
        for m in moves:
            board._make(m)
            score = -self._negamax(board, self.depth - 1, -beta, -alpha, 1)
            board._unmake()
            if score > alpha:
                alpha, best_move = score, m
        return SearchResult(best_move, alpha, self.nodes, time.perf_counter() - start)

    # ---------------------------------------------------------------- search
    def _negamax(self, board: Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if board.halfmove >= 100:
            return 0
        moves = board.legal_moves()
        if not moves:
            return -(MATE - ply) if board.in_check() else 0  # prefer quicker mates
        if depth <= 0:
            return self._quiesce(board, alpha, beta, 0)
        for m in self._order(board, moves):
            board._make(m)
            score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
            board._unmake()
            if score >= beta:
                return beta          # opponent will avoid this line: prune
            if score > alpha:
                alpha = score
        return alpha

    def _quiesce(self, board: Board, alpha: int, beta: int, qdepth: int) -> int:
        """Keep searching captures so the AI doesn't stop mid-exchange (horizon effect)."""
        self.nodes += 1
        stand_pat = evaluate(board)
        if stand_pat >= beta:
            return beta
        if stand_pat > alpha:
            alpha = stand_pat
        if qdepth >= self.max_quiescence:
            return alpha
        s = board.squares
        captures = [m for m in board.legal_moves() if s[m.to] is not None or m.flag == "ep" or m.promo]
        for m in self._order(board, captures):
            board._make(m)
            score = -self._quiesce(board, -beta, -alpha, qdepth + 1)
            board._unmake()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    @staticmethod
    def _order(board: Board, moves: List[Move]) -> List[Move]:
        """MVV-LVA: try 'most valuable victim, least valuable attacker' captures first."""
        s = board.squares

        def key(m: Move) -> int:
            k = 0
            victim = s[m.to]
            if victim is not None:
                k += 10 * PIECE_VALUES[victim.lower()] - PIECE_VALUES[s[m.frm].lower()] + 10_000
            elif m.flag == "ep":
                k += 10_000
            if m.promo:
                k += PIECE_VALUES[m.promo] + 5_000
            return k

        return sorted(moves, key=key, reverse=True)
