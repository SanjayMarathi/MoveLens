"""
A small client for UCI chess engines such as Stockfish.

UCI ("Universal Chess Interface") is a plain-text protocol over stdin/stdout:

    we send   ->  uci                     engine answers  <- uciok
    we send   ->  isready                 engine answers  <- readyok
    we send   ->  position fen <FEN>
    we send   ->  go depth 16 movetime 400
                                          engine streams  <- info depth 16 multipv 1 score cp 34 ... pv e2e4 e7e5 ...
                                          and finishes    <- bestmove e2e4

"score cp 34" means +0.34 pawns for the side to move; "score mate -3" means the side to move
gets mated in 3. With "MultiPV 2" the engine reports its two best moves (multipv 1 and 2).
"""
from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EngineLine:
    move: str                     # first move of the line, in UCI format ("e2e4")
    pv: List[str] = field(default_factory=list)  # the whole principal variation
    cp: Optional[int] = None      # score in centipawns, from the side to move's point of view
    mate: Optional[int] = None    # mate in N (positive: side to move mates; negative: gets mated)
    depth: int = 0


class EngineError(RuntimeError):
    pass


class UciEngine:
    def __init__(self, path, threads: int = 1, hash_mb: int = 64, timeout: float = 60.0):
        self.path = path
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(
                path if isinstance(path, list) else [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        except OSError as e:
            raise EngineError(f"Could not start the chess engine at {path!r}: {e}")
        # A background thread reads the engine's output so we can wait with a timeout.
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self._multipv = 1
        self.name = "engine"                                 # e.g. "Stockfish 17.1", from the engine's "id name"

        self._send("uci")
        while True:
            line = self._next_line()
            if line.startswith("id name "):
                self.name = line[len("id name "):].strip()
            if line.startswith("uciok"):
                break
        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._ready()

    # ---------------------------------------------------------------- plumbing
    def _reader(self):
        for line in self.proc.stdout:
            self._lines.put(line.strip())
        self._lines.put(None)  # engine exited

    def _send(self, command: str):
        if self.proc.poll() is not None:
            raise EngineError("The chess engine has stopped")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _next_line(self) -> str:
        try:
            line = self._lines.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise EngineError("The chess engine stopped responding")
        if line is None:
            raise EngineError("The chess engine exited unexpectedly")
        return line

    def _wait_for(self, prefix: str) -> str:
        while True:
            line = self._next_line()
            if line.startswith(prefix):
                return line

    def _ready(self):
        self._send("isready")
        self._wait_for("readyok")

    # ---------------------------------------------------------------- public
    def new_game(self):
        self._send("ucinewgame")
        self._ready()

    def analyse(self, fen: str, depth: int = 16, movetime_ms: Optional[int] = None,
                multipv: int = 2) -> List[EngineLine]:
        """Analyse a position and return the engine's best lines, best first.
        The search stops at `depth` or after `movetime_ms`, whichever comes first."""
        if multipv != self._multipv:
            self._send(f"setoption name MultiPV value {multipv}")
            self._multipv = multipv
        self._send(f"position fen {fen}")
        go = f"go depth {depth}"
        if movetime_ms:
            go += f" movetime {movetime_ms}"
        self._send(go)

        lines = {}
        while True:
            line = self._next_line()
            if line.startswith("bestmove"):
                break
            if line.startswith("info") and " pv " in line and " score " in line:
                parsed = parse_info(line)
                if parsed is not None:
                    index, engine_line = parsed
                    lines[index] = engine_line   # later (deeper) info replaces earlier
        return [lines[k] for k in sorted(lines)]

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write("quit\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=2)
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def parse_info(line: str):
    """Parse one 'info ...' line into (multipv index, EngineLine), or None if it has no usable score."""
    tokens = line.split()
    result = EngineLine(move="")
    index = 1
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == "depth":
            result.depth = int(tokens[i + 1]); i += 2
        elif t == "multipv":
            index = int(tokens[i + 1]); i += 2
        elif t == "score":
            kind, value = tokens[i + 1], int(tokens[i + 2])
            if kind == "cp":
                result.cp = value
            else:
                result.mate = value
            i += 3
            if i < len(tokens) and tokens[i] in ("lowerbound", "upperbound"):
                return None  # not an exact score; wait for the next line
        elif t == "pv":
            result.pv = tokens[i + 1:]
            break
        else:
            i += 1
    if not result.pv or (result.cp is None and result.mate is None):
        return None
    result.move = result.pv[0]
    return index, result
