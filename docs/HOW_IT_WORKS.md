# How MoveLens Works: a step-by-step learning guide

Read this next to the code. Each step covers one file: what problem it solves, the key idea, where to look, and a small exercise. Do the exercises; they're how this project becomes *yours* rather than code you were given.

```
 you paste PGN ──► pgn.py ──► chess_core.py ──► for each position: uci.py ──► Stockfish
                    (read)      (replay moves)                       (score + best 2 moves)
                                                                          │
   browser ◄── main.py ◄── review.py ◄── classify.py (win %, labels, accuracy) ◄┘
  (index.html)  (jobs)     (pipeline)    openings.py (book moves)
```

---

## Step 1: The board and the rules (`app/chess_core.py`)

**Problem:** to review a game we must replay it, which means knowing which moves are legal.

**Key ideas**
- The board is a list of 64 squares: `0 = a1`, `7 = h1`, `63 = h8`. `file = sq % 8`, `rank = sq // 8`.
- Pieces are letters: uppercase for White, lowercase for Black.
- **Legal move generation** has two stages. First generate every move that follows how the pieces move (pseudo-legal). Then play each one, check whether your own king is attacked, and undo it. Only moves that don't leave your king attacked are kept.
- `push`/`pop` change the board in place and remember how to undo. That's far faster than copying the board.
- **perft** counts every position reachable in N moves. Real engines compare these counts against known numbers to prove move generation is correct (see `tests/` in the first project).

**Read:** `legal_moves`, `_pseudo_moves`, `is_attacked`, `_make`/`_unmake`, `san`, and `parse_san` at the bottom.

**Exercise:** in a Python shell:
```python
from app.chess_core import Board, parse_san
b = Board()
for s in ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7"]:
    b.push(parse_san(b, s))
print(b); print(b.outcome())      # ('checkmate', 'w')
```
Then try `parse_san(b, "Ke2")` on a fresh board and read the error.

---

## Step 2: Reading games (`app/pgn.py`)

**Problem:** chess sites export games in PGN, which contains headers, move numbers, clock comments `{[%clk 0:09:58]}`, side variations `( ... )` and glyphs like `$1`. We only want the main line.

**Key idea:** a **tokenizer** walks the text one character at a time. It keeps track of how deep it is inside `( )` so variations can be skipped, collects `{ }` comments, and splits the rest on spaces. Each move token is passed to `parse_san`, which finds the one legal move that matches it.

**Exercise:** paste one of your own games from Chess.com or Lichess into `parse_pgn(...)` and print `.sans` and `.headers`. Then break the game on purpose (change one move) and read the error message.

---

## Step 3: Talking to Stockfish (`app/uci.py`)

**Problem:** Stockfish is a separate program. We talk to it through **UCI**, a text protocol over stdin/stdout.

Try it by hand. Run `stockfish` in a terminal and type:
```
uci
setoption name MultiPV value 2
position fen rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1
go depth 15
```
You'll see lines like `info depth 15 multipv 1 score cp -30 ... pv c7c5 g1f3 ...` and finally `bestmove c7c5`.

**Key ideas**
- `score cp -30`: −0.30 pawns **for the side to move**. We always convert to White's point of view (`from_side_to_move`).
- `score mate 3`: mate in 3.
- `MultiPV 2` returns the best **two** moves. We need the second one to detect "Great" (only-move) situations.
- A reader **thread** puts each engine output line into a queue, so we can wait with a timeout and never hang forever.

**Exercise:** change `QUALITY` in `review.py` and time a review at `fast` vs `deep`. Do any labels change?

---

## Step 4: From centipawns to win % (`app/classify.py`)

**Problem:** "lost 1 pawn" means different things in different positions.

| Eval before → after | Centipawn loss | Win % before → after | Win % loss |
|---|---|---|---|
| +0.0 → −1.0 | 100 | 50 → 41 | **9** (an inaccuracy that matters) |
| +9.0 → +8.0 | 100 | 96.5 → 95 | **1.5** (doesn't matter, still totally winning) |

`win% = 50 + 50 · (2 / (1 + e^(−0.00368208 · cp)) − 1)`

This is a sigmoid curve: steep around 0 and flat at the extremes. Lichess fitted the constant on millions of real games, so win % really is "how often players at this eval go on to win".

**Accuracy:** each move gets `103.17 · e^(−0.0435 · loss) − 3.17` (100 for a perfect move, 0 for a disaster). Game accuracy mixes a *weighted mean* (sharp moments count more) with a *harmonic mean* (one blunder pulls it down hard).

**Exercise:** print `win_percent_cp(x)` for x in −500, −200, −100, 0, 100, 200, 500 and sketch the curve.

---

## Step 5: The labels (`classify()` in `app/classify.py`)

Read `classify()` from top to bottom; the order of the checks matters:

1. **Book**: the position after the move is in the opening database → stop.
2. **Forced**: only one legal move → stop.
3. If the move is the best (or less than 1 win % from it):
   - **Brilliant** if `find_sacrifice` says you left at least 2 pawns' worth of material to be captured, you weren't already completely winning (< 97%), and you're not worse afterwards (≥ 48%).
   - **Best** if it checkmates.
   - **Great** if the engine's 2nd-best move is at least 10 win % worse, meaning this was the only good move. Obvious recaptures and replies to check don't count.
   - Otherwise **Best**.
4. Otherwise, use the win % loss: Excellent < 2, Good < 5, Inaccuracy < 10, Mistake < 20, Blunder ≥ 20.
5. **Miss**: the opponent's previous move was a mistake or blunder, your move lost ≥ 10 win % (you let them off the hook), but you're not left losing (> 30%). If you end up losing, it stays a Blunder or Mistake.

**How `find_sacrifice` works:** after your move, look at each of your pieces the opponent can legally capture. If the piece is undefended, you risk its full value. If it's defended, you risk its value minus the value of the cheapest piece that can take it (a defended knight attacked by a pawn risks 3 − 1 = 2). Subtract whatever your move captured, so a queen trade isn't a sacrifice.

**Exercises**
- Lower `BRILLIANT_MIN_SACRIFICE` to 1 and review a gambit game. What changes, and is it better or worse?
- Add a rule: a move is **Great** when it punishes the opponent's blunder (the previous label was "blunder" and you played the best move). Add a test for it in `tests/test_classify.py`.

---

## Step 6: The pipeline (`app/review.py`)

A game with *n* moves has *n + 1* positions. We analyse **every position once**:

- `analysis[i]` gives the eval **before** move *i* (assuming best play) and the engine's top 2 moves.
- `analysis[i+1]` gives the eval **after** the move that was actually played.
- loss = mover's win % before − mover's win % after.

One subtle detail: if the played move was the engine's **2nd choice**, we reuse that line's score from the *same* search, because two searches of different positions can disagree slightly and make a good move look worse than it is.

Positions where the game is over (checkmate, stalemate) are scored directly without asking the engine.

**Exercise:** add a `"key_moments"` list to the result: the 3 moves with the biggest win % swing. Then show them in the UI.

---

## Step 7: The web server (`app/main.py`)

**Problem:** a review takes 10–60 seconds, which is too long for one HTTP request (browsers and hosting proxies time out).

**Solution: background jobs.**
1. `POST /api/reviews` validates the PGN right away (so typos fail instantly), creates a `Job`, submits it to a thread pool and returns the job id.
2. A worker thread runs `review_game`, updating `job.done` as each position is analysed.
3. The browser polls `GET /api/reviews/{id}` every 0.7 s and draws the progress bar.

Each worker thread owns **its own Stockfish process** (`threading.local`), because a single engine can only think about one position at a time. `ENGINE_WORKERS` controls how many reviews run in parallel. Extra requests wait in the queue, and there's a cap (`MAX_QUEUED`) so the server can't be overloaded.

**Exercise:** jobs live in memory, so they disappear on restart. Store finished results in SQLite (`sqlite3` is built into Python) so review links keep working after a restart.

---

## Step 8: The page (`static/`)

No framework and no build step: plain HTML, one stylesheet, and a few ES modules.

```
static/index.html      the markup: front page sections + the review screen
static/css/app.css     tokens, scenes (sky, dusk, night...), layout
static/js/main.js      wires everything up; starts reviews; opens a review from the URL
static/js/landing.js   the form, importing games by username, recent reviews, the demo board
static/js/review.js    the review screen: state, coach, move list, summary, engine lines
static/js/board.js     the board itself: drawing, drag and drop, promotion picker, arrows
static/js/prefs.js     saved preferences and the theme picker
static/js/api.js       fetch wrappers for the server's JSON API
```

Things worth reading:

- **`board.js` knows nothing about reviews.** You hand it a FEN and it draws 64 squares. When you move a piece it calls `onMove` with a legal-move entry. Legal moves come from the server (`POST /api/legal`) once per position, so the browser needs no chess rules.
- **`review.js` keeps its whole state in one object `S`:** `ply` (which move of the real game is shown), `line` (moves you played yourself after that ply), and `retry` (set while you look for a better move than a mistake). Every `render()` simply redraws the board, coach, move list and graph from `S`, which is why stepping back and forth never gets out of sync.
- **Your own moves** are applied instantly (the legal-move entry already contains the new FEN), then judged by `POST /api/explore`, which uses the same `judge_move()` as the full review. A pending move shows a spinner until the label arrives.
- **Board size** is computed in CSS from both the width and the height of the window (`--bs` in `app.css`), so the board and both player bars always fit the screen.
- **Scenes** are JPEG backgrounds in `static/bg/`, drawn by `tools/make_backgrounds.js` (gradients, noise-based clouds, stars, hills rendered to JPEG through headless Edge or Chrome).

**Exercise:** add a "Show only mistakes" filter to the move list, or a button that replays every mistake of the game as a Retry puzzle, one after another.

---

## Step 9: Training a model (`ml/`)

**Do we need ML for the labels?** No. The "intelligence" is Stockfish (whose evaluation is itself a neural network called NNUE), plus the rules above. To *train* a label classifier you'd need millions of moves already labelled by someone, and no site publishes its labels. So the honest design is engine + rules, with ML where real labelled data exists.

**Where real data exists: ratings.** Lichess publishes every rated game (public domain), with both players' ratings, and many games already contain Stockfish evals. So we can learn:

> *given how a player played in this game → what rating do they usually have?*

1. `ml/build_dataset.py` streams a huge PGN file. For each game with evals it computes each player's per-move win % losses (skipping book and forced moves) and turns them into features (`app/features.py`): number of moves, average loss, accuracy, share of moves losing < 1/2/5/10/20 %, worst move, and time control. Each row is labelled with the player's real rating.
2. `ml/train_rating_model.py` splits the rows 80/20 into training and test sets, trains a **gradient-boosted tree regressor**, and reports the **MAE** (average error in rating points) next to a baseline that always guesses the average rating. If the model doesn't beat the baseline clearly, it hasn't learned anything.
3. The server loads `ml/rating_model.joblib` at startup and adds "Game rating (est.)" to each review.

**Important:** features must be computed **the same way** in training (from Lichess evals) and when serving (from our Stockfish analysis). That's why both use only per-move win % losses.

**Ideas to improve it** (good interview material):
- Train a separate model per time control (bullet ratings differ from classical).
- Add features: time-trouble moves (from `[%clk]`), how sharp the position was, endgame accuracy.
- Instead of one rating per game, predict a range (quantile regression) and show "≈1400–1600".

---

## Step 10: Deploying

The `Dockerfile` is the recipe: start from Python, `apt-get install stockfish`, install requirements, copy the code, and run uvicorn. Any platform that runs Docker can host it. See the README for Hugging Face Spaces (free, 2 CPUs) and Render.

Things to know:
- Free tiers sleep when unused, so the first request afterwards is slow.
- Stockfish is CPU-heavy. `MAX_QUALITY` and `ENGINE_WORKERS` keep a small server responsive.

---

## Questions you'll likely be asked in interviews

- **Why win % instead of centipawns?** Centipawns over-penalise mistakes in already-decided positions. Win % reflects what actually changes the result.
- **How do you detect a brilliant move?** Best move + a real material sacrifice (static exchange check on hanging pieces) + not already winning + not worse afterwards.
- **Why background jobs?** Analysis takes longer than typical HTTP timeouts. Jobs plus polling are simple, robust behind proxies, and let us limit concurrency.
- **Why one engine per worker thread?** A UCI engine handles one search at a time. Sharing one engine between threads would mix up their answers.
- **How did you test without Stockfish?** A tiny stand-in engine speaks the same UCI protocol (`tests/fake_engine.py`), so the parser, pipeline and API are all tested end to end.
- **What would you do at scale?** Cache analyses by position (openings repeat constantly), move Stockfish to the browser with WebAssembly, store results in a database, and use a real task queue (Redis + RQ/Celery).
