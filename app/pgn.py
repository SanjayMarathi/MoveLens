"""
PGN reader.

PGN ("Portable Game Notation") is the text format every chess site exports, e.g.

    [White "Magnus"]
    [Black "Hikaru"]
    1. e4 {[%clk 0:03:00]} e5 2. Nf3 (2. f4 exf4) Nc6 $1 1-0

We keep the headers and the main line of moves, and throw away side variations "( ... )"
and annotation glyphs "$1". Comments "{ ... }" are kept per move, because Lichess exports put
engine evaluations in them ("[%eval 0.31]"), which the ML training script uses.

A plain move list with no headers ("1.e4 e5 2.Nf3 Nc6") is also accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .chess_core import START_FEN, Board, Move, parse_san

HEADER_RE = re.compile(r'^\s*\[(\w+)\s+"((?:[^"\\]|\\.)*)"\s*\]\s*$')
MOVE_NUMBER_RE = re.compile(r"^\d+\.+")
RESULTS = {"1-0", "0-1", "1/2-1/2", "½-½", "*"}
MAX_PLIES = 600


@dataclass
class ParsedGame:
    headers: Dict[str, str]
    start_fen: str
    moves: List[Move]                 # the moves, as engine Move objects
    sans: List[str]                   # the moves in clean SAN, e.g. "Nxe5+"
    comments: List[str] = field(default_factory=list)  # comment text after each move ("" if none)


def _split_first_game(text: str):
    """Return (header lines, movetext) of the first game in the text."""
    headers, movetext, in_moves = [], [], False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if HEADER_RE.match(stripped):
            if in_moves:          # a header after moves means a second game starts: stop
                break
            headers.append(stripped)
        elif stripped:
            in_moves = True
            movetext.append(line)
    return headers, "\n".join(movetext)


def _tokenize(movetext: str):
    """Yield ('move', text) and ('comment', text) tokens from the main line only."""
    i, n, depth = 0, len(movetext), 0
    word = []

    def flush():
        if word:
            token = "".join(word)
            word.clear()
            return token
        return None

    while i < n:
        c = movetext[i]
        if c == "{":                                  # { comment }
            end = movetext.find("}", i + 1)
            end = n if end == -1 else end
            token = flush()
            if token and depth == 0:
                yield "move", token
            if depth == 0:
                yield "comment", movetext[i + 1:end].strip()
            i = end + 1
            continue
        if c == ";":                                  # ; comment to end of line
            end = movetext.find("\n", i)
            end = n if end == -1 else end
            token = flush()
            if token and depth == 0:
                yield "move", token
            if depth == 0:
                yield "comment", movetext[i + 1:end].strip()
            i = end
            continue
        if c == "(":                                  # start of a side variation: skip it
            token = flush()
            if token and depth == 0:
                yield "move", token
            depth += 1
        elif c == ")":
            flush()
            depth = max(0, depth - 1)
        elif c.isspace():
            token = flush()
            if token and depth == 0:
                yield "move", token
        elif depth == 0:
            word.append(c)
        i += 1
    token = flush()
    if token and depth == 0:
        yield "move", token


def parse_pgn(text: str) -> ParsedGame:
    if not text or not text.strip():
        raise ValueError("Paste a game first (PGN or a move list like '1. e4 e5 2. Nf3').")
    header_lines, movetext = _split_first_game(text)
    headers = {}
    for line in header_lines:
        key, value = HEADER_RE.match(line).groups()
        headers[key] = value.replace('\\"', '"')

    start_fen = headers.get("FEN") or START_FEN
    try:
        board = Board(start_fen)
    except ValueError as e:
        raise ValueError(f"The FEN header is not valid: {e}")

    moves: List[Move] = []
    sans: List[str] = []
    comments: List[str] = []
    for kind, token in _tokenize(movetext):
        if kind == "comment":
            if comments:
                comments[-1] = (comments[-1] + " " + token).strip()
            continue
        token = MOVE_NUMBER_RE.sub("", token)        # "12." or "12...", also glued "12.e4"
        if not token or token.startswith("$"):        # annotation glyphs like $1
            continue
        if token in RESULTS:
            break
        if len(moves) >= MAX_PLIES:
            raise ValueError(f"Games longer than {MAX_PLIES // 2} moves are not supported.")
        try:
            move = parse_san(board, token)
        except ValueError as e:
            number = board.fullmove
            side = "White" if board.turn == "w" else "Black"
            raise ValueError(f"Move {number} for {side} ('{token}') can't be played: {e}.")
        sans.append(board.san(move))
        board.push(move)
        moves.append(move)
        comments.append("")

    if not moves:
        raise ValueError("No moves found. Paste the game's PGN or move list.")
    return ParsedGame(headers, start_fen, moves, sans, comments)


EVAL_RE = re.compile(r"\[%eval\s+(#?-?[\d.]+)\]")


def comment_eval(comment: str) -> Optional[str]:
    """Extract a Lichess '[%eval 0.31]' or '[%eval #-3]' annotation, if present."""
    m = EVAL_RE.search(comment or "")
    return m.group(1) if m else None
