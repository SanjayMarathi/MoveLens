"""
Step 1 of training: turn a Lichess database file into a table of features + real ratings.

Get data (free, public domain): https://database.lichess.org  -> "Standard chess" -> pick a month.
About 6% of those games already have Stockfish evaluations in "[%eval ...]" comments, so we don't
need to run an engine ourselves. Decompress first:   zstd -d lichess_db_standard_rated_2024-01.pgn.zst

    python -m ml.build_dataset lichess_db_standard_rated_2024-01.pgn ml/dataset.csv --max-games 200000

Each usable game gives two rows (White and Black): features..., rating
"""
from __future__ import annotations

import argparse
import csv
import sys
from typing import Iterator

from app.classify import Score
from app.features import FEATURE_NAMES, player_features
from app.openings import OpeningBook
from app.pgn import comment_eval, parse_pgn


def iter_games(path: str) -> Iterator[str]:
    """Yield one game's PGN text at a time (files can be many GB, so stream them)."""
    chunk, seen_moves = [], False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("[Event ") and seen_moves:
                yield "".join(chunk)
                chunk, seen_moves = [], False
            if line.strip() and not line.startswith("["):
                seen_moves = True
            chunk.append(line)
    if chunk and seen_moves:
        yield "".join(chunk)


def eval_to_score(text: str) -> Score:
    """Lichess evals are from White's view: '0.31' (pawns) or '#-3' (mate)."""
    if text.startswith("#"):
        return Score(mate=int(text[1:]))
    return Score(cp=int(round(float(text) * 100)))


def game_rows(pgn_text: str, book: OpeningBook):
    if "[%eval" not in pgn_text:
        return []
    game = parse_pgn(pgn_text)
    headers = game.headers
    try:
        ratings = {"w": int(headers["WhiteElo"]), "b": int(headers["BlackElo"])}
    except (KeyError, ValueError):
        return []

    from app.chess_core import Board
    board = Board(game.start_fen)
    prev_score = Score(cp=20)                 # starting position is about +0.2
    losses = {"w": [], "b": []}
    in_book = True
    for move, comment in zip(game.moves, game.comments):
        mover = board.turn
        forced = len(board.legal_moves()) == 1
        board.push(move)
        ev = comment_eval(comment)
        if ev is None:
            if board.outcome()[0] != "ongoing":
                break                         # game ended by mate/stalemate: no eval needed
            return []                         # incomplete annotations: skip the game
        score = eval_to_score(ev)
        in_book = in_book and book.contains(board.fen())
        if not in_book and not forced:
            losses[mover].append(max(0.0, prev_score.win_for(mover) - score.win_for(mover)))
        prev_score = score

    rows = []
    for color in ("w", "b"):
        feats = player_features(losses[color], headers.get("TimeControl"))
        if feats is not None:
            rows.append(feats + [ratings[color]])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pgn_file")
    ap.add_argument("out_csv")
    ap.add_argument("--max-games", type=int, default=100_000, help="stop after this many usable games")
    args = ap.parse_args(argv)

    book = OpeningBook().load()
    used = scanned = 0
    with open(args.out_csv, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(FEATURE_NAMES + ["rating"])
        for pgn_text in iter_games(args.pgn_file):
            scanned += 1
            try:
                rows = game_rows(pgn_text, book)
            except ValueError:
                continue                       # broken PGN: skip
            if rows:
                writer.writerows(rows)
                used += 1
                if used % 1000 == 0:
                    print(f"{used} games used / {scanned} scanned", file=sys.stderr)
                if used >= args.max_games:
                    break
    print(f"Done: {used} games ({scanned} scanned) -> {args.out_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
