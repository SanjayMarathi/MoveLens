"""
A complete chess rules engine written from scratch (no third-party chess libraries).

Supports every rule of chess:
  * legal move generation for all pieces (moves that leave your king in check are rejected)
  * castling (with all the "can't castle through/out of check" rules)
  * en passant
  * pawn promotion (to queen, rook, bishop or knight)
  * check, checkmate and stalemate
  * draws by the fifty-move rule, threefold repetition and insufficient material
  * FEN import/export and Standard Algebraic Notation (SAN) for move history

Board layout: squares are numbered 0..63, where 0 = a1, 7 = h1, 56 = a8, 63 = h8.
Pieces are single characters: uppercase = white (PNBRQK), lowercase = black (pnbrqk).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

WHITE, BLACK = "w", "b"
FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

KNIGHT_STEPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_STEPS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


# --------------------------------------------------------------------------- helpers
def sq_name(sq: int) -> str:
    """0 -> 'a1', 63 -> 'h8'."""
    return FILES[sq % 8] + str(sq // 8 + 1)


def parse_sq(name: str) -> int:
    """'e4' -> 28. Raises ValueError for anything that isn't a real square."""
    if len(name) != 2 or name[0] not in FILES or name[1] not in "12345678":
        raise ValueError(f"Invalid square: {name!r}")
    return FILES.index(name[0]) + (int(name[1]) - 1) * 8


def color_of(piece: str) -> str:
    return WHITE if piece.isupper() else BLACK


def opposite(color: str) -> str:
    return BLACK if color == WHITE else WHITE


def _step_table(steps):
    """For every square, the squares reachable with one of the given (file, rank) steps."""
    table = []
    for sq in range(64):
        f, r = sq % 8, sq // 8
        table.append([(r + dr) * 8 + (f + df) for df, dr in steps
                      if 0 <= f + df < 8 and 0 <= r + dr < 8])
    return table


def _ray_table(dirs):
    """For every square, a list of rays (one per direction) ordered outward from the square."""
    table = []
    for sq in range(64):
        f, r = sq % 8, sq // 8
        rays = []
        for df, dr in dirs:
            ray, nf, nr = [], f + df, r + dr
            while 0 <= nf < 8 and 0 <= nr < 8:
                ray.append(nr * 8 + nf)
                nf += df
                nr += dr
            rays.append(ray)
        table.append(rays)
    return table


# Precomputed once at import time -> much faster move generation.
KNIGHT_TARGETS = _step_table(KNIGHT_STEPS)
KING_TARGETS = _step_table(KING_STEPS)
ROOK_RAYS = _ray_table(ROOK_DIRS)
BISHOP_RAYS = _ray_table(BISHOP_DIRS)


# --------------------------------------------------------------------------- move
@dataclass(frozen=True)
class Move:
    frm: int
    to: int
    promo: Optional[str] = None  # 'q', 'r', 'b' or 'n'
    flag: str = ""               # "", "double" (pawn 2-step), "ep" (en passant), "castle"

    def uci(self) -> str:
        return sq_name(self.frm) + sq_name(self.to) + (self.promo or "")

    def __repr__(self) -> str:
        return f"Move({self.uci()})"


# --------------------------------------------------------------------------- board
class Board:
    def __init__(self, fen: str = START_FEN):
        self.load_fen(fen)

    # ---------------------------------------------------------------- FEN
    def load_fen(self, fen: str) -> None:
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError("Invalid FEN: expected at least 4 fields")
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError("Invalid FEN: expected 8 ranks")

        squares: List[Optional[str]] = [None] * 64
        for i, row in enumerate(rows):
            rank, f = 7 - i, 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch in "PNBRQKpnbrqk":
                    if f > 7:
                        raise ValueError("Invalid FEN: rank too long")
                    squares[rank * 8 + f] = ch
                    f += 1
                else:
                    raise ValueError(f"Invalid FEN: bad character {ch!r}")
            if f != 8:
                raise ValueError("Invalid FEN: each rank must have 8 squares")
        if squares.count("K") != 1 or squares.count("k") != 1:
            raise ValueError("Invalid FEN: each side needs exactly one king")
        if parts[1] not in (WHITE, BLACK):
            raise ValueError("Invalid FEN: side to move must be 'w' or 'b'")
        castling = "" if parts[2] == "-" else parts[2]
        if any(c not in "KQkq" for c in castling):
            raise ValueError("Invalid FEN: bad castling field")

        self.squares = squares
        self.turn = parts[1]
        self.castling = castling
        self.ep: Optional[int] = None if parts[3] == "-" else parse_sq(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self._stack: list = []                       # undo information
        self._positions = [self._position_key()]     # for threefold repetition

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for f in range(8):
                p = self.squares[rank * 8 + f]
                if p is None:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
            if empty:
                row += str(empty)
            rows.append(row)
        ep = sq_name(self.ep) if self.ep is not None else "-"
        return f"{'/'.join(rows)} {self.turn} {self.castling or '-'} {ep} {self.halfmove} {self.fullmove}"

    def copy(self) -> "Board":
        return Board(self.fen())

    # ---------------------------------------------------------------- queries
    def king_square(self, color: str) -> int:
        return self.squares.index("K" if color == WHITE else "k")

    def is_attacked(self, sq: int, by: str) -> bool:
        """Is square `sq` attacked by any piece of colour `by`?"""
        s = self.squares
        f = sq % 8
        if by == WHITE:
            if f > 0 and sq >= 9 and s[sq - 9] == "P":
                return True
            if f < 7 and sq >= 7 and s[sq - 7] == "P":
                return True
            knight, king, rook, bishop, queen = "N", "K", "R", "B", "Q"
        else:
            if f < 7 and sq <= 54 and s[sq + 9] == "p":
                return True
            if f > 0 and sq <= 56 and s[sq + 7] == "p":
                return True
            knight, king, rook, bishop, queen = "n", "k", "r", "b", "q"

        for t in KNIGHT_TARGETS[sq]:
            if s[t] == knight:
                return True
        for t in KING_TARGETS[sq]:
            if s[t] == king:
                return True
        for ray in ROOK_RAYS[sq]:
            for t in ray:
                p = s[t]
                if p is not None:
                    if p == rook or p == queen:
                        return True
                    break
        for ray in BISHOP_RAYS[sq]:
            for t in ray:
                p = s[t]
                if p is not None:
                    if p == bishop or p == queen:
                        return True
                    break
        return False

    def in_check(self, color: Optional[str] = None) -> bool:
        color = color or self.turn
        return self.is_attacked(self.king_square(color), opposite(color))

    @property
    def last_move(self) -> Optional[Move]:
        return self._stack[-1][0] if self._stack else None

    @property
    def move_count(self) -> int:
        return len(self._stack)

    # ---------------------------------------------------------------- move generation
    def legal_moves(self) -> List[Move]:
        us, them = self.turn, opposite(self.turn)
        legal = []
        for m in self._pseudo_moves():
            self._make(m)
            if not self.is_attacked(self.king_square(us), them):
                legal.append(m)
            self._unmake()
        return legal

    def _pseudo_moves(self) -> List[Move]:
        """All moves that follow piece-movement rules, ignoring whether the king is left in check."""
        s = self.squares
        white = self.turn == WHITE
        moves: List[Move] = []
        for sq, p in enumerate(s):
            if p is None or p.isupper() != white:
                continue
            kind = p.lower()
            if kind == "p":
                self._pawn_moves(sq, moves)
            elif kind == "n":
                for t in KNIGHT_TARGETS[sq]:
                    q = s[t]
                    if q is None or q.isupper() != white:
                        moves.append(Move(sq, t))
            elif kind == "k":
                for t in KING_TARGETS[sq]:
                    q = s[t]
                    if q is None or q.isupper() != white:
                        moves.append(Move(sq, t))
                self._castling_moves(sq, moves)
            else:
                if kind == "r":
                    rays = ROOK_RAYS[sq]
                elif kind == "b":
                    rays = BISHOP_RAYS[sq]
                else:
                    rays = ROOK_RAYS[sq] + BISHOP_RAYS[sq]
                for ray in rays:
                    for t in ray:
                        q = s[t]
                        if q is None:
                            moves.append(Move(sq, t))
                        else:
                            if q.isupper() != white:
                                moves.append(Move(sq, t))
                            break
        return moves

    def _pawn_moves(self, sq: int, moves: List[Move]) -> None:
        s = self.squares
        white = self.turn == WHITE
        step = 8 if white else -8
        start_rank, promo_rank = (1, 7) if white else (6, 0)
        f, r = sq % 8, sq // 8

        t = sq + step
        if 0 <= t < 64 and s[t] is None:
            self._add_pawn_move(sq, t, promo_rank, moves)
            if r == start_rank and s[t + step] is None:
                moves.append(Move(sq, t + step, flag="double"))
        for df in (-1, 1):
            if not 0 <= f + df < 8:
                continue
            t = sq + step + df
            if not 0 <= t < 64:
                continue
            q = s[t]
            if q is not None and q.isupper() != white:
                self._add_pawn_move(sq, t, promo_rank, moves)
            elif t == self.ep:
                moves.append(Move(sq, t, flag="ep"))

    @staticmethod
    def _add_pawn_move(frm: int, to: int, promo_rank: int, moves: List[Move]) -> None:
        if to // 8 == promo_rank:
            for pr in "qrbn":
                moves.append(Move(frm, to, pr))
        else:
            moves.append(Move(frm, to))

    def _castling_moves(self, sq: int, moves: List[Move]) -> None:
        if not self.castling:
            return
        s = self.squares
        if self.turn == WHITE:
            base, ks, qs, rook, enemy = 0, "K", "Q", "R", BLACK
        else:
            base, ks, qs, rook, enemy = 56, "k", "q", "r", WHITE
        king_sq = base + 4
        if sq != king_sq:
            return
        if ks in self.castling and s[base + 5] is None and s[base + 6] is None \
                and s[base + 7] == rook \
                and not any(self.is_attacked(x, enemy) for x in (base + 4, base + 5, base + 6)):
            moves.append(Move(king_sq, base + 6, flag="castle"))
        if qs in self.castling and s[base + 1] is None and s[base + 2] is None \
                and s[base + 3] is None and s[base] == rook \
                and not any(self.is_attacked(x, enemy) for x in (base + 4, base + 3, base + 2)):
            moves.append(Move(king_sq, base + 2, flag="castle"))

    # ---------------------------------------------------------------- make / unmake
    def push(self, move: Move) -> None:
        """Play a move and record it for repetition detection (use for real game moves)."""
        self._make(move)
        self._positions.append(self._position_key())

    def pop(self) -> Move:
        """Take back the last move played with push()."""
        if not self._stack:
            raise IndexError("No moves to undo")
        self._positions.pop()
        return self._unmake()

    def _make(self, m: Move) -> None:
        s = self.squares
        p = s[m.frm]
        white = p.isupper()
        if m.flag == "ep":
            cap_sq = m.to - 8 if white else m.to + 8
            captured = s[cap_sq]
            s[cap_sq] = None
        else:
            captured = s[m.to]
        self._stack.append((m, captured, self.castling, self.ep, self.halfmove))

        s[m.to] = (m.promo.upper() if white else m.promo) if m.promo else p
        s[m.frm] = None

        if m.flag == "castle":
            rf, rt = (m.to + 1, m.to - 1) if m.to % 8 == 6 else (m.to - 2, m.to + 1)
            s[rt], s[rf] = s[rf], None

        if self.castling:
            c = self.castling
            if p == "K":
                c = c.replace("K", "").replace("Q", "")
            elif p == "k":
                c = c.replace("k", "").replace("q", "")
            for corner in (m.frm, m.to):
                if corner == 0:
                    c = c.replace("Q", "")
                elif corner == 7:
                    c = c.replace("K", "")
                elif corner == 56:
                    c = c.replace("q", "")
                elif corner == 63:
                    c = c.replace("k", "")
            self.castling = c

        self.ep = (m.frm + m.to) // 2 if m.flag == "double" else None
        self.halfmove = 0 if (p in "Pp" or captured) else self.halfmove + 1
        if not white:
            self.fullmove += 1
        self.turn = BLACK if white else WHITE

    def _unmake(self) -> Move:
        m, captured, castling, ep, halfmove = self._stack.pop()
        s = self.squares
        p = s[m.to]
        white = p.isupper()
        if m.promo:
            p = "P" if white else "p"
        s[m.frm] = p
        if m.flag == "ep":
            s[m.to] = None
            s[m.to - 8 if white else m.to + 8] = captured
        else:
            s[m.to] = captured
        if m.flag == "castle":
            rf, rt = (m.to + 1, m.to - 1) if m.to % 8 == 6 else (m.to - 2, m.to + 1)
            s[rf], s[rt] = s[rt], None
        self.castling, self.ep, self.halfmove = castling, ep, halfmove
        if not white:
            self.fullmove -= 1
        self.turn = WHITE if white else BLACK
        return m

    # ---------------------------------------------------------------- game end
    def _position_key(self) -> Tuple:
        """Identity of a position for repetition (en passant only counts if it is capturable)."""
        ep = None
        if self.ep is not None:
            pawn = "P" if self.turn == WHITE else "p"
            pushed = self.ep - 8 if self.turn == WHITE else self.ep + 8
            f = pushed % 8
            for df in (-1, 1):
                if 0 <= f + df < 8 and self.squares[pushed + df] == pawn:
                    ep = self.ep
        return (tuple(self.squares), self.turn, self.castling, ep)

    def is_insufficient_material(self) -> bool:
        others = [(sq, p) for sq, p in enumerate(self.squares) if p and p not in "Kk"]
        if not others:
            return True                                   # K vs K
        if len(others) == 1 and others[0][1] in "NnBb":
            return True                                   # K+minor vs K
        if all(p in "Bb" for _, p in others):             # only bishops, all on one square colour
            return len({(sq % 8 + sq // 8) % 2 for sq, _ in others}) == 1
        return False

    def is_threefold_repetition(self) -> bool:
        return self._positions.count(self._positions[-1]) >= 3

    def outcome(self) -> Tuple[str, Optional[str]]:
        """Returns (status, winner). status is 'ongoing', 'checkmate', 'stalemate',
        'fifty_move', 'threefold_repetition' or 'insufficient_material'."""
        if not self.legal_moves():
            if self.in_check():
                return "checkmate", opposite(self.turn)
            return "stalemate", None
        if self.halfmove >= 100:
            return "fifty_move", None
        if self.is_threefold_repetition():
            return "threefold_repetition", None
        if self.is_insufficient_material():
            return "insufficient_material", None
        return "ongoing", None

    # ---------------------------------------------------------------- notation
    def san(self, m: Move, legal: Optional[List[Move]] = None) -> str:
        """Standard Algebraic Notation for a legal move in the current position, e.g. 'Nbd7', 'exd5', 'O-O', 'e8=Q#'."""
        if legal is None:
            legal = self.legal_moves()
        s = self.squares
        p = s[m.frm]
        kind = p.upper()
        if m.flag == "castle":
            text = "O-O" if m.to % 8 == 6 else "O-O-O"
        else:
            capture = s[m.to] is not None or m.flag == "ep"
            if kind == "P":
                text = (FILES[m.frm % 8] + "x" if capture else "") + sq_name(m.to)
                if m.promo:
                    text += "=" + m.promo.upper()
            else:
                rivals = [o for o in legal if o.to == m.to and o.frm != m.frm and s[o.frm] == p]
                dis = ""
                if rivals:
                    if not any(o.frm % 8 == m.frm % 8 for o in rivals):
                        dis = FILES[m.frm % 8]
                    elif not any(o.frm // 8 == m.frm // 8 for o in rivals):
                        dis = str(m.frm // 8 + 1)
                    else:
                        dis = sq_name(m.frm)
                text = kind + dis + ("x" if capture else "") + sq_name(m.to)
        self._make(m)
        if self.in_check():
            text += "#" if not self.legal_moves() else "+"
        self._unmake()
        return text

    def find_move(self, frm: str, to: str, promo: Optional[str] = None) -> Optional[Move]:
        """Look up a legal move from square names, e.g. find_move('e7', 'e8', 'q')."""
        f, t = parse_sq(frm), parse_sq(to)
        for m in self.legal_moves():
            if m.frm == f and m.to == t and m.promo == promo:
                return m
        return None

    def __str__(self) -> str:
        lines = []
        for rank in range(7, -1, -1):
            lines.append(f"{rank + 1} " + " ".join(self.squares[rank * 8 + f] or "." for f in range(8)))
        lines.append("  a b c d e f g h")
        return "\n".join(lines)


def perft(board: Board, depth: int) -> int:
    """Count leaf nodes of the move tree; the standard way to prove a move generator is correct."""
    if depth == 0:
        return 1
    moves = board.legal_moves()
    if depth == 1:
        return len(moves)
    total = 0
    for m in moves:
        board._make(m)
        total += perft(board, depth - 1)
        board._unmake()
    return total


# --------------------------------------------------------------------------- SAN parsing
import re as _re

_SAN_RE = _re.compile(r"^([NBRQK])?([a-h])?([1-8])?x?([a-h][1-8])(?:=?([NBRQ]))?$")
_UCI_RE = _re.compile(r"^([a-h][1-8])([a-h][1-8])([qrbn])?$")


def parse_san(board: "Board", text: str) -> Move:
    """Turn a move written by a human ('Nf3', 'exd5', 'O-O', 'e8=Q+', 'Nbd7!?', or UCI 'e2e4')
    into the matching legal Move. Raises ValueError if it is illegal or ambiguous."""
    s = text.strip().replace("e.p.", "")
    s = _re.sub(r"[+#!?]+$", "", s)
    legal = board.legal_moves()

    if s in ("O-O", "0-0", "O-O-O", "0-0-0"):
        target_file = 6 if s.count("-") == 1 else 2
        for m in legal:
            if m.flag == "castle" and m.to % 8 == target_file:
                return m
        raise ValueError(f"Castling ({text}) is not legal here")

    uci = _UCI_RE.match(s)
    if uci:
        frm, to, promo = parse_sq(uci.group(1)), parse_sq(uci.group(2)), uci.group(3)
        for m in legal:
            if m.frm == frm and m.to == to and m.promo == promo:
                return m
        raise ValueError(f"{text} is not legal here")

    match = _SAN_RE.match(s)
    if not match:
        raise ValueError(f"Can't read move {text!r}")
    piece, from_file, from_rank, dest, promo = match.groups()
    piece = piece or "P"
    to = parse_sq(dest)
    promo = promo.lower() if promo else None
    found = [
        m for m in legal
        if m.to == to
        and board.squares[m.frm].upper() == piece
        and (from_file is None or FILES[m.frm % 8] == from_file)
        and (from_rank is None or str(m.frm // 8 + 1) == from_rank)
        and m.promo == promo
    ]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ValueError(f"{text} is not legal here")
    raise ValueError(f"{text} is ambiguous here")
