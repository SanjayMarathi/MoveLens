---
title: MoveLens Chess Review
emoji: ♟️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Free chess game review with a playable analysis board
---

# MoveLens: Chess Game Review

Paste a game, or pull it from Chess.com or Lichess by username, and get a full review: every move labelled **Brilliant, Great, Best, Excellent, Good, Book, Inaccuracy, Mistake, Miss or Blunder**, the better move shown on the board, an evaluation bar and graph, a coach comment for each move, and an accuracy score for each player. Then **play on the board yourself**: try other moves, retry your mistakes, and see the engine's verdict straight away.

> New to the code? Read **[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)**. It goes through the project one step at a time, with exercises.

## Features

- **Import** a game by pasting a PGN, uploading a `.pgn` file, or typing a **Chess.com / Lichess username** and picking one of the 20 latest games
- **Choose your view:** type your username and the board opens from your side, or pick White / Black yourself
- **Stockfish 19** analysis of every position at four depths (Fast, Standard, Deep, Maximum)
- **Move labels** from win-percentage loss, plus rules for Brilliant (sound sacrifices), Great (only move), Miss, Book (3,800 named openings) and Forced
- **A live board:** drag or click pieces at any point of the game. Your move is judged like the rest of the game. Promotions, castling and en passant all work
- **Retry** any mistake: you are put back before it and asked to find a better move
- **Engine lines:** the top three continuations for any position, including positions you create. Click a line to play it
- Coach with **Explain** (winning chance before and after, evaluation, accuracy) and **Best** (arrow)
- **Summary:** accuracy per player, accuracy by game phase (opening / middlegame / endgame), move-quality counts, key moments you can jump to
- Player bars with **captured pieces**, material lead and **clocks** (when the PGN has them)
- Evaluation bar and clickable graph, figurine move list, auto-play, key-moment navigation (`[` `]`)
- Right-click arrows and square highlights, move **sounds** (generated in the browser, no audio files)
- **Themes:** 6 scenes (Sky, Meadow, Dusk, Night, Slate, Paper), 12 boards, 6 piece sets. Saved in the browser. A link can carry a look: `/?scene=night&board=green&pieces=merida`
- **Remembers everything in your browser** until you clear site data: saved reviews, the side lines and retries you were working on, every engine answer (seen positions never hit the server twice), your unsent form, and the app itself, so it **opens offline**. See the footer for what is stored
- Copy or download an **annotated PGN**; installable as an app (manifest + icons)
- The URL remembers the review and the current move (`#r=<id>&ply=<n>`)
- A front page that explains how to use it, what every label means, and answers common questions

## Run locally

You need Python 3.10+ and Stockfish.

```bash
# 1. Install Stockfish
#    Windows: download from https://stockfishchess.org/download/ and note the path to the .exe
#    macOS:   brew install stockfish
#    Ubuntu:  sudo apt install stockfish

# 2. Install Python packages
pip install -r requirements-dev.txt

# 3. Start the server (set STOCKFISH_PATH only if stockfish isn't on your PATH)
#    Windows PowerShell:  $env:STOCKFISH_PATH="C:\path\to\stockfish.exe"
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and click **Try a famous game** (it opens instantly, no engine needed). The API docs are at http://127.0.0.1:8000/docs.

To run the tests (they use a small built-in stand-in engine, so Stockfish isn't needed):

```bash
pytest -v
```

Or run everything in Docker (no Stockfish install needed; the image downloads the newest official Stockfish):

```bash
docker build -t movelens .
docker run -p 7860:7860 movelens        # then open http://localhost:7860
```

## Deploy for free

The `Dockerfile` installs Stockfish and starts the server, so any host that runs Docker works.

### Option A: Hugging Face Spaces (recommended: the most CPU and memory)

**Full step-by-step guide: [docs/DEPLOY.md](docs/DEPLOY.md).** In short:

1. Create a Hugging Face account with a **PRO** plan (needed to create a Docker Space) and a **write access token**.
2. Create a new **Docker (Blank)** Space on **CPU basic** hardware (no hourly cost). *CPU Upgrade* (8 vCPU, $0.03/hour) is faster.
3. Push this folder to it:
   ```bash
   git init -b main && git add . && git commit -m "MoveLens"
   git remote add space https://huggingface.co/spaces/<your-username>/movelens
   git push --force space main       # username + token as the password
   ```
4. Nothing to configure on the free CPU: the server detects its 2-CPU limit and caps depth at Deep and the queue at 6. Never click a hardware *Upgrade* button.
5. Wait for the build (5 to 8 minutes). Your app is live at `https://<your-username>-movelens.hf.space`.

The top of this README (the block between `---` lines) is the Space's configuration; keep it.

Images (the backgrounds and icons) are committed as base64 text, because Hugging Face rejects binary files in git; see [docs/DEPLOY.md](docs/DEPLOY.md#why-some-images-are-b64-files).

### Option B: Render

1. Push the project to GitHub.
2. On https://render.com choose **New → Blueprint** and select the repository. Render reads `render.yaml` and builds the Dockerfile.
3. The free plan has very little CPU and 512 MB of memory, so `render.yaml` caps the depth at `fast`, uses a small hash table, and selects Debian's lighter Stockfish. It also sleeps after about 15 minutes idle, so the first visit afterwards takes about a minute.

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `STOCKFISH_PATH` | found on PATH | Engine location (`/opt/stockfish` in Docker) |
| `STOCKFISH_FALLBACK` | none | A second engine to try if the first can't start (`/usr/games/stockfish` in Docker) |
| `ENGINE_WORKERS` | 1 | Reviews analysed in parallel (one Stockfish process each) |
| `ENGINE_THREADS` | CPUs this container may use / workers, at most 4 | CPU threads per Stockfish process (the container's real CPU limit is detected) |
| `ENGINE_HASH_MB` | 128 | Memory per Stockfish process |
| `MAX_QUALITY` | `deep` on a 2-CPU host, else `max` | Highest depth allowed: `fast` (12), `standard` (16), `deep` (20) or `max` (24) |
| `MAX_QUEUED` | 6 on a 2-CPU host, else 20 | Reviews allowed to wait at once |

## How the labels work (short version)

1. Stockfish scores each position in centipawns (+100 means White is up a pawn).
2. Each score is converted into a **win %** with `50 + 50·(2/(1+e^(−0.00368·cp)) − 1)`. A pawn matters a lot in an equal position and hardly at all when you're already up a queen, and win % reflects that.
3. **Loss** is the difference between the mover's win % after the best move and after the move they actually played.

| Label | Rule |
|---|---|
| Best | Stockfish's top move |
| Excellent / Good | lost < 2 / < 5 win % |
| Inaccuracy / Mistake / Blunder | lost < 10 / < 20 / ≥ 20 win % |
| Brilliant | best move **and** leaves at least 2 pawns' worth of material to be taken, you weren't already completely winning, and you're not worse afterwards |
| Great | best move, and every other move is at least 10 win % worse (the only move) |
| Miss | the opponent just made a mistake and your move lost ≥ 10 win %, giving the advantage back |
| Book | the position is in the opening database |
| Forced | the only legal move |

The thresholds are constants in `app/classify.py`, so you can tune them. These rules are an approximation; no site publishes its exact algorithm, so labels will sometimes differ from what you see elsewhere.

## Project structure

```
app/
  chess_core.py   rules engine written from scratch: legal moves, SAN, FEN, check/mate/draws
  pgn.py          PGN reader (headers, comments, variations, clocks)
  uci.py          client for the UCI protocol Stockfish speaks
  classify.py     win %, accuracy, and the labelling rules
  openings.py     opening book from data/openings.tsv
  review.py       pipeline: parse → analyse → label → summarise (and judge_move, shared with the live board)
  explore.py      the live board: legal moves, judging your own moves, engine lines
  importer.py     recent games from Chess.com and Lichess by username
  sysinfo.py      real CPU limit inside a container, default limits for small hosts
  assets.py       serves images stored as base64 text (Hugging Face rejects binary files in git)
  features.py     features + loader for the ML rating model
  main.py         FastAPI server, background job queue, live-board endpoints
static/
  index.html      the page (front page + review screen)
  css/app.css     styles and scenes
  js/             ES modules: main, landing, review, board, prefs, api, store (IndexedDB), history, sound, util
  sw.js           service worker (offline + instant loading); the server fills in its version and file list
  bg/             scene backgrounds: *.jpg (git-ignored, made by tools/make_backgrounds.js) and *.jpg.b64 (the committed text copy)
  pieces/         SVG piece sets (authors and licences in CREDITS.md)
  data/opera.json a pre-computed review used by "Try a famous game" and the demo board
data/openings.tsv 3,800 named openings (Lichess, public domain)
ml/               dataset builder + training script for the rating estimator
tools/            make_backgrounds.js and make_icons.js (regenerate the scene images and app icons)
tests/            pytest suite + a stand-in UCI engine
Dockerfile, render.yaml
```

## API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/reviews` | `{"pgn": "...", "quality": "deep"}` → `{"id": ..., "status": "queued"}` |
| GET | `/api/reviews/{id}` | progress (`done`/`total`), then the full annotated game |
| POST | `/api/legal` | `{"fen": ...}` → every legal move with its SAN and resulting FEN |
| POST | `/api/explore` | `{"fen": ..., "uci": "e2e4"}` → your move, labelled like in a review |
| POST | `/api/analyse` | `{"fen": ..., "count": 3}` → the engine's best lines |
| GET | `/api/import/{chesscom\|lichess}?user=name` | a player's 20 most recent standard games |
| GET | `/api/health` | engine name, opening book, model, depth limit |

## Regenerating the backgrounds

The scene images in `static/bg/` are drawn procedurally (gradients, noise-based clouds, stars, hills) and rendered to JPEG by headless Edge/Chrome:

```bash
node tools/make_backgrounds.js            # all scenes; or: node tools/make_backgrounds.js sky night
```

## Training the rating model (optional)

The move labels **don't need training**: Stockfish is the "model", and its evaluations are already very strong. Training is useful for something the engine can't tell you: **how strong a player looked in this game** (an estimated rating).

```bash
# 1. Download a month of rated games (public domain) from https://database.lichess.org, then decompress:
zstd -d lichess_db_standard_rated_2024-01.pgn.zst

# 2. Build features from games that already contain Stockfish evals (about 6% of games)
python -m ml.build_dataset lichess_db_standard_rated_2024-01.pgn ml/dataset.csv --max-games 200000

# 3. Train (gradient-boosted trees) and save ml/rating_model.joblib
pip install -r requirements-ml.txt        # scikit-learn + joblib, only needed for training
python -m ml.train_rating_model ml/dataset.csv
```

Restart the server (the Docker image installs the extra libraries by itself when `ml/rating_model.joblib` exists), and reviews will show "Game rating (est.)". The training script prints the model's error next to a "guess the average" baseline, so you can see how much it really learned. See `docs/HOW_IT_WORKS.md` (step 9) for ideas to improve it.

## Ideas to extend

- Save reviews in SQLite/PostgreSQL on the server so share links survive restarts (today they survive in the owner's browser)
- Run Stockfish in the browser (WebAssembly) so the server only does labelling, and analysis costs nothing to host
- A "Practice my mistakes" mode that chains the Retry puzzles from all your saved games
- Opening explorer and per-opening statistics across your saved reviews
- Stream progress with WebSockets instead of polling

## Resume bullets

- Built **MoveLens**, a full-stack chess game review platform (FastAPI, Stockfish, vanilla JS) that classifies every move from Brilliant to Blunder using engine evaluations converted to win probability, with sacrifice detection, only-move detection and an opening book of 3,800 lines.
- Added an interactive analysis board: drag-and-drop moves judged live by the engine, a Retry mode for mistakes, engine lines, and one-click import of Chess.com and Lichess games.
- Implemented a from-scratch chess rules engine and PGN parser (verified against perft benchmarks), a UCI engine client, and a background job queue with per-worker engine processes and progress reporting.
- Designed a responsive, themeable interface (procedurally generated scene backgrounds, 12 boards, 6 piece sets) and containerised the app with Docker for free-tier deployment.
- Trained a gradient-boosted regression model on Lichess games to estimate a player's rating from per-move win-probability loss.
