"""
Web server (FastAPI).

Reviewing a game takes from a few seconds to a few minutes (one engine search per position), too long
for a single HTTP request. So reviews run as background JOBS:

    POST /api/reviews        {"pgn": "...", "quality": "deep"}  -> {"id": "...", "status": "queued"}
    GET  /api/reviews/{id}   -> {"status": "running", "progress": {"done": 31, "total": 80}}
                             -> {"status": "done", "result": {...the annotated game...}}

The browser polls the GET endpoint about once a second and draws a progress bar.

The live board (playing your own moves on a reviewed game) is answered straight away by a separate engine, so
it never waits behind a running review:

    POST /api/legal          {"fen": ...}                          -> every legal move, with SAN and the new FEN
    POST /api/explore        {"fen": ..., "uci": "e2e4"}           -> your move, labelled like in a review
    POST /api/analyse        {"fen": ..., "count": 3}              -> the engine's best lines
    GET  /api/import/{site}?user=name                              -> a player's recent games (chesscom | lichess)

Environment variables:
    STOCKFISH_PATH      path to the engine binary (default: found on PATH, or /usr/games/stockfish)
    STOCKFISH_FALLBACK  a second engine to try if the first can't start (e.g. the CPU lacks AVX2)
    ENGINE_WORKERS      reviews analysed in parallel; each has its own Stockfish (default 1)
    ENGINE_THREADS      CPU threads per Stockfish (default: the CPUs this container may use, shared between workers, at most 4)
    ENGINE_HASH_MB      memory per Stockfish for its transposition table (default 128)
    MAX_QUALITY         highest analysis quality allowed: fast | standard | deep | max (default: deep on a 2-CPU host, else max)
    MAX_QUEUED          reviews allowed to wait at once (default: 6 on a 2-CPU host, else 20)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .assets import StaticFilesWithEncodedImages, encoded_twin
from .explore import engine_lines, explore_move, legal_moves_info
from .features import RatingModel
from .importer import ImportProblem, recent_games
from .openings import OpeningBook, position_key
from .pgn import parse_pgn
from .review import LIVE_QUALITY, QUALITY, review_game
from .sysinfo import default_limits, effective_cpus
from .uci import EngineError, EngineLine, UciEngine

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
QUALITY_ORDER = ["fast", "standard", "deep", "max"]

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish") or "/usr/games/stockfish"
STOCKFISH_FALLBACK = os.environ.get("STOCKFISH_FALLBACK") or ""
ENGINE_WORKERS = int(os.environ.get("ENGINE_WORKERS", "1"))
CPUS = effective_cpus()
ENGINE_THREADS = int(os.environ.get("ENGINE_THREADS") or max(1, min(4, CPUS // max(1, ENGINE_WORKERS))))
ENGINE_HASH_MB = int(os.environ.get("ENGINE_HASH_MB", "128"))
_default_quality, _default_queue = default_limits(CPUS)
MAX_QUALITY = os.environ.get("MAX_QUALITY") or _default_quality
if MAX_QUALITY not in QUALITY_ORDER:
    MAX_QUALITY = _default_quality
MAX_QUEUED = int(os.environ.get("MAX_QUEUED") or _default_queue)
MAX_JOBS_KEPT = 300
MAX_PGN_CHARS = 100_000
LIVE_TIMEOUT = 60

app = FastAPI(
    title="MoveLens API",
    description="Paste a game, get every move classified (Brilliant ... Blunder) with Stockfish, then play on the board.",
    version="2.0.0",
)

book = OpeningBook()
rating_model = RatingModel(ROOT / "ml" / "rating_model.joblib")
executor = ThreadPoolExecutor(max_workers=ENGINE_WORKERS)                      # reviews
live_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live")   # your own moves, engine lines
_engines = threading.local()                                                   # one Stockfish per worker thread
engine_name: Optional[str] = None                                              # e.g. "Stockfish 17.1", once known


def _capped(quality: str) -> str:
    return MAX_QUALITY if QUALITY_ORDER.index(quality) > QUALITY_ORDER.index(MAX_QUALITY) else quality


def start_engine(hash_mb: int, threads: Optional[int] = None) -> UciEngine:
    """Start Stockfish, falling back to the second engine if the first can't run on this machine."""
    global engine_name
    paths = [STOCKFISH_PATH] + ([STOCKFISH_FALLBACK] if STOCKFISH_FALLBACK and STOCKFISH_FALLBACK != STOCKFISH_PATH else [])
    error: Optional[EngineError] = None
    for path in paths:
        try:
            engine = UciEngine(path, threads=threads or ENGINE_THREADS, hash_mb=hash_mb)
            engine_name = engine.name
            return engine
        except EngineError as e:
            error = e
    raise error  # type: ignore[misc]


def get_engine(live: bool = False) -> UciEngine:
    engine = getattr(_engines, "engine", None)
    if engine is None or engine.proc.poll() is not None:
        engine = (start_engine(max(16, ENGINE_HASH_MB // 2), max(1, ENGINE_THREADS // 2)) if live
                  else start_engine(ENGINE_HASH_MB))
        _engines.engine = engine
    return engine


def _startup() -> None:
    book.load()                                   # takes a few seconds; don't block the server starting
    try:
        start_engine(16).close()                  # learn the engine's name, and fail early in the logs if it can't run
    except EngineError as e:
        print(f"[movelens] WARNING: the chess engine could not start: {e}", flush=True)


threading.Thread(target=_startup, daemon=True).start()


# --------------------------------------------------------------------------- reviews (background jobs)
class Job:
    def __init__(self, pgn: str, quality: str, total: int):
        self.id = uuid.uuid4().hex[:12]
        self.pgn = pgn
        self.quality = quality
        self.status = "queued"           # queued -> running -> done | error
        self.done = 0
        self.total = total
        self.result = None
        self.error: Optional[str] = None
        self.created = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "quality": self.quality,
            "progress": {"done": self.done, "total": self.total},
            "result": self.result, "error": self.error,
        }


jobs: "OrderedDict[str, Job]" = OrderedDict()
jobs_lock = threading.Lock()


def run_job(job: Job) -> None:
    job.status = "running"
    q = QUALITY[job.quality]

    def progress(done, total):
        job.done, job.total = done, total

    try:
        book.wait()
        for attempt in range(2):                  # restart the engine once if it crashed
            try:
                engine = get_engine()
                engine.new_game()
                job.result = review_game(
                    job.pgn,
                    lambda fen: engine.analyse(fen, depth=q.depth, movetime_ms=q.movetime_ms, multipv=2),
                    book=book, rating_model=rating_model, progress=progress,
                )
                job.result["engine"] = engine_name
                job.result["quality"] = job.quality
                break
            except EngineError:
                _engines.engine = None
                if attempt == 1:
                    raise
        job.status = "done"
    except EngineError as e:
        job.status, job.error = "error", f"Engine problem: {e}"
    except Exception as e:  # noqa: BLE001 - report anything to the user rather than hang
        job.status, job.error = "error", f"Analysis failed: {e}"
    finally:
        job.pgn = ""                               # free memory


# --------------------------------------------------------------------------- live board
_cache: "OrderedDict[tuple, List[EngineLine]]" = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 400


def _cached_analyser(engine: UciEngine, quality: str) -> Callable[[str, int], List[EngineLine]]:
    q = LIVE_QUALITY[quality]

    def analyse(fen: str, count: int = 2) -> List[EngineLine]:
        key = (position_key(fen), count, q.depth, q.movetime_ms)
        with _cache_lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key]
        lines = engine.analyse(fen, depth=q.depth, movetime_ms=q.movetime_ms, multipv=count)
        with _cache_lock:
            _cache[key] = lines
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        return lines

    return analyse


def run_live(quality: str, work: Callable[[Callable[[str, int], List[EngineLine]]], dict]) -> dict:
    """Run `work(analyse)` on the live engine and wait for the answer."""
    quality = _capped(quality)

    def task():
        for attempt in range(2):
            try:
                return work(_cached_analyser(get_engine(live=True), quality))
            except EngineError:
                _engines.engine = None
                if attempt == 1:
                    raise

    try:
        return live_executor.submit(task).result(timeout=LIVE_TIMEOUT)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except EngineError as e:
        raise HTTPException(503, f"Engine problem: {e}")
    except (TimeoutError, FutureTimeout):
        raise HTTPException(504, "The engine took too long. Try a lower depth.")


# --------------------------------------------------------------------------- API
class ReviewRequest(BaseModel):
    pgn: str = Field(..., description="PGN text or a plain move list like '1. e4 e5 2. Nf3'")
    quality: Literal["fast", "standard", "deep", "max"] = "deep"


class FenRequest(BaseModel):
    fen: str = Field(..., max_length=120)


class ExploreRequest(FenRequest):
    uci: str = Field(..., pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")
    quality: Literal["fast", "standard", "deep", "max"] = "standard"
    previous_label: Optional[str] = None
    recapture_square: Optional[str] = Field(None, pattern=r"^[a-h][1-8]$")


class LinesRequest(FenRequest):
    count: int = Field(3, ge=1, le=5)
    quality: Literal["fast", "standard", "deep", "max"] = "standard"


@app.get("/", include_in_schema=False)
def index():
    # X-MoveLens lets the browser's service worker tell this page from a "Space is waking up" page of the host
    return FileResponse(STATIC_DIR / "index.html", headers={"X-MoveLens": "1"})


def shell_files() -> list:
    """The files the service worker keeps in the browser so the app opens instantly and works offline."""
    files = ["/", "/static/css/app.css", "/static/data/opera.json", "/static/bg/sky.jpg", "/static/icon.svg"]
    files += [f"/static/js/{p.name}" for p in sorted((STATIC_DIR / "js").glob("*.js"))]
    files += [f"/static/pieces/cburnett/{p.name}" for p in sorted((STATIC_DIR / "pieces" / "cburnett").glob("*.svg"))]
    return [f for f in files if _static_exists(f)]                   # a missing file would make the whole install fail


def _static_path(url_path: str) -> Path:
    return STATIC_DIR / "index.html" if url_path == "/" else STATIC_DIR / url_path[len("/static/"):]


def _static_exists(url_path: str) -> bool:
    """True if the file exists, or exists as base64 text (images are committed that way, see assets.py)."""
    return _static_path(url_path).exists() or (url_path != "/" and encoded_twin(STATIC_DIR, url_path[len("/static/"):]) is not None)


def shell_version(files: list) -> str:
    """Changes whenever any shell file (or the service worker itself) changes, so each deploy refreshes the cache."""
    digest = hashlib.sha1()
    for f in files + ["/static/sw.js"]:
        p = _static_path(f)
        if not p.exists() and f != "/":
            p = encoded_twin(STATIC_DIR, f[len("/static/"):]) or p
        if p.exists():
            st = p.stat()
            digest.update(f"{f}:{st.st_size}:{st.st_mtime_ns}".encode())
    return digest.hexdigest()[:12]


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    files = shell_files()
    source = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    body = source.replace("__VERSION__", shell_version(files)).replace("__PRECACHE__", json.dumps(files))
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFilesWithEncodedImages(directory=STATIC_DIR), name="static")      # page assets: css, js, pieces, backgrounds


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "engine": STOCKFISH_PATH,
        "engine_found": Path(STOCKFISH_PATH).exists(),
        "engine_name": engine_name,
        "engine_threads": ENGINE_THREADS,
        "opening_book_positions": len(book.positions),
        "rating_model": rating_model.available,
        "max_quality": MAX_QUALITY,
        "max_queued": MAX_QUEUED,
        "cpus": CPUS,
    }


@app.post("/api/reviews", summary="Start reviewing a game")
def create_review(req: ReviewRequest):
    if len(req.pgn) > MAX_PGN_CHARS:
        raise HTTPException(413, "That PGN is too long.")
    try:
        game = parse_pgn(req.pgn)                  # validate now so typos are reported instantly
    except ValueError as e:
        raise HTTPException(400, str(e))
    quality = _capped(req.quality)

    with jobs_lock:
        waiting = sum(1 for j in jobs.values() if j.status in ("queued", "running"))
        if waiting >= MAX_QUEUED:
            raise HTTPException(503, "The server is busy. Please try again in a minute.")
        job = Job(req.pgn, quality, total=len(game.moves) + 1)
        jobs[job.id] = job
        while len(jobs) > MAX_JOBS_KEPT:
            jobs.popitem(last=False)
    executor.submit(run_job, job)
    return job.to_dict()


@app.get("/api/reviews/{job_id}", summary="Progress and result of a review")
def get_review(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Review not found (the server may have restarted).")
    data = job.to_dict()
    if job.status == "queued":                      # how many reviews must finish before this one starts
        with jobs_lock:
            ahead = sum(1 for j in jobs.values() if j.status in ("queued", "running") and j.created < job.created)
        data["ahead"] = max(0, ahead - ENGINE_WORKERS + 1)
    return data


@app.post("/api/legal", summary="Every legal move from a position")
def legal(req: FenRequest):
    try:
        return legal_moves_info(req.fen)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/explore", summary="Judge a move you played on the board")
def explore(req: ExploreRequest):
    book.wait()
    return run_live(req.quality, lambda analyse: explore_move(
        req.fen, req.uci, analyse, book=book,
        previous_label=req.previous_label, recapture_square=req.recapture_square))


@app.post("/api/analyse", summary="The engine's best lines for a position")
def analyse_position_lines(req: LinesRequest):
    return run_live(req.quality, lambda analyse: engine_lines(req.fen, analyse, req.count))


@app.get("/api/import/{site}", summary="A player's recent games from Chess.com or Lichess")
def import_games(site: str, user: str):
    try:
        return {"site": site, "user": user.strip(), "games": recent_games(site, user.strip())}
    except ImportProblem as e:
        raise HTTPException(e.status, str(e))
