"""
Opening book: detects "Book" moves and names the opening.

data/openings.tsv is the public-domain Lichess opening list (~3,800 named lines, e.g.
"C60  Ruy Lopez  1. e4 e5 2. Nf3 Nc6 3. Bb5"). We replay every line once at startup and remember
each position reached. During a review, a move is "book" while the game stays inside that set.
Positions are compared (not move sequences), so transpositions are recognised too.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from .chess_core import START_FEN, Board, parse_san

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "openings.tsv"


def position_key(fen: str) -> str:
    """Board + side to move + castling + en passant (ignores the move counters)."""
    return " ".join(fen.split()[:4])


class OpeningBook:
    def __init__(self, path: Path = DATA_FILE):
        self.path = path
        self.positions: Dict[str, Optional[Tuple[str, str]]] = {}   # key -> (eco, name) or None
        self._loaded = threading.Event()

    def load(self) -> "OpeningBook":
        positions: Dict[str, Optional[Tuple[str, str]]] = {}
        named: Dict[str, Tuple[str, str]] = {}
        if self.path.exists():
            for row in self.path.read_text(encoding="utf-8").splitlines()[1:]:
                parts = row.split("\t")
                if len(parts) != 3:
                    continue
                eco, name, line = parts
                board = Board(START_FEN)
                try:
                    for token in line.split():
                        if token[0].isdigit():
                            continue
                        board.push(parse_san(board, token))
                        positions.setdefault(position_key(board.fen()), None)
                except ValueError:
                    continue
                named[position_key(board.fen())] = (eco, name)
        positions.update(named)
        self.positions = positions
        self._loaded.set()
        return self

    def wait(self, timeout: float = 60) -> None:
        self._loaded.wait(timeout)

    def contains(self, fen: str) -> bool:
        return position_key(fen) in self.positions

    def name(self, fen: str) -> Optional[Tuple[str, str]]:
        return self.positions.get(position_key(fen))
