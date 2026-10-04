"""
A tiny stand-in for Stockfish, used only by the tests.

It speaks the same UCI protocol (run this file as a program) and can also be called directly
via `analyse(fen)`. It's much weaker than Stockfish (2-ply search + capture search), but that's
enough to exercise the whole review pipeline without installing an engine.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chess_core import Board  # noqa: E402
from app.uci import EngineLine  # noqa: E402
from tests.mini_ai import MATE, ChessAI  # noqa: E402

DEPTH = 2


def analyse(fen: str, multipv: int = 2):
    board = Board(fen)
    ai = ChessAI(depth=DEPTH, randomness=False)
    scored = []
    for move in ai._order(board, board.legal_moves()):
        board._make(move)
        score = -ai._negamax(board, DEPTH - 1, -MATE - 1, MATE + 1, 1)
        reply = ChessAI(depth=1, randomness=False).choose_move(board).move if board.legal_moves() else None
        board._unmake()
        scored.append((score, move, reply))
    scored.sort(key=lambda t: -t[0])
    lines = []
    for score, move, reply in scored[:multipv]:
        pv = [move.uci()] + ([reply.uci()] if reply else [])
        if abs(score) > MATE - 100:
            plies = MATE - abs(score)
            mate = (plies + 1) // 2
            lines.append(EngineLine(move=move.uci(), pv=pv, mate=mate if score > 0 else -mate, depth=DEPTH))
        else:
            lines.append(EngineLine(move=move.uci(), pv=pv, cp=score, depth=DEPTH))
    return lines


def main():
    multipv, fen = 1, None
    for raw in sys.stdin:
        cmd = raw.strip()
        if cmd == "uci":
            print("id name FakeFish\nuciok", flush=True)
        elif cmd == "isready":
            print("readyok", flush=True)
        elif cmd.startswith("setoption name MultiPV value"):
            multipv = int(cmd.split()[-1])
        elif cmd.startswith("position fen"):
            fen = cmd[len("position fen "):]
        elif cmd.startswith("go"):
            lines = analyse(fen, multipv)
            print("info string thinking", flush=True)
            for i, line in enumerate(lines, 1):
                print(f"info depth 1 multipv {i} score cp 0 upperbound pv {line.move}")
                score = f"mate {line.mate}" if line.mate is not None else f"cp {line.cp}"
                print(f"info depth {DEPTH} seldepth 4 multipv {i} score {score} nodes 100 nps 1000 "
                      f"pv {' '.join(line.pv)}")
            print(f"bestmove {lines[0].move if lines else '(none)'}", flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()
