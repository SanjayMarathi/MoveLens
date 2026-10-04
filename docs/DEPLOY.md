# Deploying MoveLens to Hugging Face Spaces (free)

About 15 minutes. At the end you will have a public link like
`https://<your-username>-movelens.hf.space` that anyone can open.

**What you need:**
* A Hugging Face **PRO** subscription ($9/month at the time of writing). Hugging Face now requires a paid plan to *create* a Docker Space (PRO for a personal account, Team/Enterprise for an organisation). The Space itself, on the default CPU hardware, has no extra hourly cost. (If you cancel PRO later, check Hugging Face's current rules for what happens to existing Docker Spaces.)
* A computer with Git installed (`git --version` should print a version), and this project folder.

---

## 1. Create a Hugging Face account

1. Go to <https://huggingface.co/join> and sign up (email + password, or Google/GitHub).
2. Open the confirmation email and click the link. Spaces cannot be created until the email is verified.
3. Remember your **username** (top-right menu). Below, `YOUR_USERNAME` means this.

## 2. Create an access token

Git needs this instead of a password.

1. Open <https://huggingface.co/settings/tokens> → **Create new token**.
2. Token type **Write**, any name (for example `movelens-deploy`) → **Create token**.
3. **Copy it now** (it starts with `hf_`). It is shown once. Treat it like a password: never put it in a file in the project.

## 3. Create the Space

1. Open <https://huggingface.co/new-space>.
2. Fill in the form:

   | Field | Choose |
   |---|---|
   | Owner | your username |
   | Space name | `movelens` |
   | License | anything you like (for example MIT) |
   | **Space SDK** | **Docker**, then the **Blank** template |
   | **Space hardware** | **CPU basic · 2 vCPU · 16 GB** (you can upgrade later, see step 6) |
   | Visibility | **Public** (a private Space needs a login to open) |

3. Click **Create Space**. (If it asks you to upgrade your plan, your PRO subscription is not active on this account yet.) You land on an empty Space page. That is normal.

## 4. Put the project into a git repository

Open PowerShell in the project folder:

```powershell
cd E:\chess-review

git init -b main
git config user.name  "Your Name"          # only if git has never been set up on this computer
git config user.email "you@example.com"    # same
git add .
git commit -m "MoveLens"
```

You may see lines like *"LF will be replaced by CRLF"*. They are harmless: the project's `.gitattributes` makes sure the repository always stores Unix line endings, which the Dockerfile needs.

Check what is going in (about 130 files, nothing large):

```powershell
git ls-files | Measure-Object -Line
```

## 5. Push it to the Space

```powershell
git remote add space https://huggingface.co/spaces/YOUR_USERNAME/movelens
git push --force space main
```

* **Username:** your Hugging Face username. **Password:** the token from step 2 (paste it; nothing shows while you type).
  Windows may show a sign-in window from Git Credential Manager instead. Use the same values.
* `--force` is needed **only this first time**: a new Space already contains a placeholder `README.md`, which this replaces.
* The project's `README.md` starts with the block Spaces reads its settings from (`sdk: docker`, `app_port: 7860`). Do not delete it.

**Got "Your push was rejected because it contains binary files"?** Hugging Face Spaces refuse image files in git, and the first version of this project had four `.jpg` backgrounds and two `.png` icons. They are now committed as text (`*.b64`) and decoded by the server, so a fresh repository pushes cleanly. If you already made your first commit before this fix, that commit still contains the images, so rewrite it (your files on disk are not touched):

```powershell
cd E:\chess-review
git rm -r --cached . -q          # forget what git was tracking (the files stay on disk)
git add .                        # add again; .gitignore now leaves the 6 real images out
git commit --amend -m "MoveLens" # replace the single commit
git push --force space main
```

## 6. Stay on the free CPU (nothing to configure)

A new Space starts on **CPU basic: 2 vCPU, 16 GB RAM, no hourly cost**. Leave it there. **Do not click any "Upgrade" or hardware button** in *Settings*; only upgraded hardware is billed.

You do not need to set any variables. When MoveLens starts it detects the 2-CPU limit and chooses sensible limits by itself:

| Detected automatically | On the free 2-CPU Space |
|---|---|
| Deepest analysis offered | **Deep** (a request for "Maximum" is quietly lowered to Deep) |
| Engine threads | 2 for the review engine, 1 for the engine that answers your own moves |
| Reviews allowed to wait | 6 (more get a polite "server is busy"), and each waiting person sees how many reviews are ahead of theirs |
| Real speed (measured on the live free Space) | a 47-move game (94 plies) at **Deep in 115 seconds**; other games scale with their length |

(You *can* override them with Space variables: `MAX_QUALITY`, `MAX_QUEUED`, `ENGINE_THREADS`. Saving a variable restarts the Space.)

**How to be sure you are not being billed for hardware:** *Settings → Space hardware* should say **CPU basic**, and your billing page should show no Spaces usage. Your PRO subscription is the only charge. GPUs, ZeroGPU and inference credits are not useful here: Stockfish runs on the CPU.

*(Optional, later: if you ever want it faster, "CPU Upgrade" has 8 vCPU for $0.03 per hour. Set `ENGINE_WORKERS=2` and `MAX_QUALITY=max` and give it a sleep time so it stops billing when idle.)*

## 7. Watch it build

The Space page shows **Building**. Click **Logs** to follow it. The first build takes about **5 to 8 minutes**: it installs Python packages and downloads Stockfish 19 (80 MB). Later builds are faster because layers are cached.

When the badge turns **Running**, the app is live at:

* `https://YOUR_USERNAME-movelens.hf.space`: the **direct link**. Use this one and share this one.
* `https://huggingface.co/spaces/YOUR_USERNAME/movelens`: the same app inside the Hugging Face page.

## 8. Check that it works

Open the direct link and tick off:

- [ ] The front page loads with the sky background and the animated demo board.
- [ ] `https://YOUR_USERNAME-movelens.hf.space/api/health` shows `"engine_name":"Stockfish 19"` and `"engine_found":true`.
- [ ] **Try a famous game** opens instantly and you can play a move on the board.
- [ ] Paste a short game (or use the Chess.com tab with your username) and press **Review game**. The progress bar should move. At **Deep** a 40-move game takes roughly 1.5 to 3 minutes on the free server.
- [ ] Reload the page: the review comes back exactly where you left it.

## 9. Updating the app later

After any change:

```powershell
git add .
git commit -m "Describe the change"
git push space main          # no --force from now on
```

The Space rebuilds on its own. Visitors get the new version the next time they open the page: the app's saved copy in their browser refreshes automatically (the server gives it a new version number whenever a file changes).

Tip: keep a copy on GitHub as well. Add it as a second remote (`git remote add origin <github-url>`) and push to both: `git push origin main` and `git push space main`.

---

## Why some images are `.b64` files

Hugging Face Spaces reject binary files in a Space's git repository (the alternative is their Xet storage tool). So the backgrounds and app icons are committed as base64 **text** next to the real image (`sky.jpg.b64`), and the server decodes them when a browser asks for `sky.jpg` (`app/assets.py`). On your own computer the real files are used and are git-ignored. If you change an image, run the script in `tools/` again (it writes both), and the test suite checks that the two never disagree.

---

## What the browser remembers

All of this is stored **in the visitor's own browser** (IndexedDB, localStorage and the service worker cache), never on the server. It stays until the person clears the site's data (in Chrome: *Settings → Privacy and security → Delete browsing data → Cookies and other site data*, or the site's lock icon → *Site settings → Delete data*).

| Remembered | Where | Effect |
|---|---|---|
| The app itself (page, scripts, styles, pieces, a background) | service worker cache | opens instantly, and **opens offline** |
| Every finished review (up to 60) | IndexedDB | opens instantly, even when the Space is asleep or was rebuilt |
| Where you were in each review: side lines, retries, tab, board side, engine-lines switch | IndexedDB | reload or come back later and continue exactly there |
| Every engine answer (legal moves, your moves judged, engine lines) | IndexedDB (last 4,000) | a position you have seen is answered instantly, offline, and costs the server nothing |
| The unsent form (pasted PGN, Chess.com/Lichess tab, username, last list of games) | IndexedDB | still there after a reload |
| Themes, board side, depth, sound, username | localStorage | the same look next time |

The footer of the front page shows how much is stored and has **Forget positions** and **Delete saved reviews** buttons.

Notes:
* Use the **direct `.hf.space` link**. Inside the huggingface.co page the app runs in a frame, and browsers keep that frame's storage separate (and sometimes stricter).
* A private/incognito window forgets everything when it is closed. That is the browser's rule, not a bug.
* The app asks the browser to treat its data as "persistent" so it is not discarded when disk space is low; browsers decide whether to agree.

---

## What PRO gives you (and what it doesn't)

Useful for MoveLens:
* **Creating Docker Spaces** (the reason it is needed).
* **Protected visibility:** the app stays public at its `.hf.space` address, but the *source code* is hidden. Choose **Public** instead if this is a portfolio project and you want people to read the code. Settings → visibility.
* **Spaces Dev Mode:** edit the running Space from VS Code, without rebuilding for every change. Optional, since you can test locally with Docker.

Not useful here: ZeroGPU quota, inference credits, bigger private storage (MoveLens keeps user data in the visitor's browser).

PRO does **not** include free upgraded CPU. Faster hardware is billed per hour on top and is optional (see step 6).

## Hardware and cost facts to know

* **CPU basic** gives 2 vCPU and 16 GB RAM. Spaces on it **sleep after 48 hours without visitors** and wake on the next visit, which takes around a minute. MoveLens copes with that: a returning visitor's browser opens the saved app within about 3 seconds, shows a "server is waking up" note, and the sample game, saved reviews and positions already seen work meanwhile. A first-time visitor sees Hugging Face's own waking-up page for that minute.
* Outbound requests are allowed on ports 80, 443 and 8080 only. The Chess.com and Lichess import uses 443, so it works.
* The Space's disk is temporary (50 GB, not persistent). That is fine: nothing important is stored there. The server keeps finished reviews in memory for a while; the visitor's browser keeps its own copy.
* The Space is open to anyone with the link, so anyone can run reviews. On the free 2-CPU hardware the server lets 6 reviews wait at once and politely says "busy" after that.
* The server must be able to reach `api.chess.com` and `lichess.org` for the username import. Hugging Face allows outbound requests.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Your push was rejected because it contains binary files` | See the box under step 5: rewrite the first commit with the four commands there. Never add `.jpg`/`.png` files to the repository; keep images as `.b64` text (the scripts in `tools/` create both). |
| `remote: Invalid username or password` | Use the **token** as the password, not your account password. Make sure it has **Write** access. |
| `refusing to merge unrelated histories` / `rejected ... fetch first` | You forgot `--force` on the **first** push. |
| Build fails at the Stockfish download | Press **Factory rebuild** (Space *Settings*) to retry. The image falls back to Debian's older Stockfish automatically if the download fails, so the app still starts. |
| Status **Runtime error** | Open **Logs → Container** and read the last lines. Most often a mistyped variable value. |
| The page is blank inside huggingface.co | Open the **direct `.hf.space` link** instead. |
| Reviews feel slow | Pick **Standard** (about 30 seconds) or **Fast** in the depth menu. Or set the Space variable `MAX_QUALITY=standard` so visitors get the quicker depth by default. |
| "The server is waking up" note | Normal after a quiet spell on free hardware. It disappears by itself within about a minute. |
| "The server is busy" | Six reviews are already waiting. Try again in a few minutes. |
| "That review isn't available any more" | The Space restarted and forgot the server-side copy. Reviews saved in the visitor's browser still open from the *Recent reviews* list. |
| You pushed a token by accident | Revoke it at <https://huggingface.co/settings/tokens> and create a new one. |

## Other free hosts

The same Dockerfile works elsewhere. **Render** (see `render.yaml`) has only 512 MB of memory, so the blueprint caps the depth at Fast and uses the lighter Debian Stockfish. **Google Cloud Run** and **Oracle Cloud Always Free** also run it (card required; check their current free limits).
