"""
Public usage numbers shown on the front page: games reviewed, moves analysed, users, and who is online now.

    games    reviews that finished
    moves    moves the engine judged: every move of a reviewed game, plus each move played on the live board
    users    browsers that have opened MoveLens (each makes a random id and is counted once)
    online   browsers with MoveLens open and visible right now (each open tab sends a heartbeat)

Nothing personal is stored. The browser sends only random ids it made itself; the totals are three integers.

Where the totals are kept:
    STATS_FILE   a small JSON file (default: /data/movelens-stats.json when a /data disk is mounted, as on a
                 Hugging Face Space with persistent storage, else a file in the system temp folder)
    STATS_REPO   a private Hugging Face dataset that also keeps the totals, because a free Space loses its disk on
    HF_TOKEN     every restart. Needs a token with write access. Inside a Space, STATS_REPO defaults to
                 "<space owner>/movelens-stats", so adding the HF_TOKEN secret is enough.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

ONLINE_WINDOW = 75            # seconds without a heartbeat before a tab no longer counts as online
MAX_TABS = 20_000             # memory bound for the "online" table
NEW_USERS_PER_IP = 30         # new users one network address may add per day (stops a script inflating the count)
SAVE_EVERY = 30               # seconds between saves to the local file (only when something changed)
SYNC_EVERY = 600              # seconds between saves to the Hugging Face dataset (only when something changed)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
COUNTERS = ("games", "moves", "users")


def valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(ID_RE.match(value))


def _counts(data: object) -> Dict[str, int]:
    """The three counters from saved data, ignoring anything that isn't a non-negative integer."""
    data = data if isinstance(data, dict) else {}
    return {k: data[k] if isinstance(data.get(k), int) and data[k] >= 0 else 0 for k in COUNTERS}


class Stats:
    """Totals = base + pending. `base` is the last total known to be saved (in the Hub dataset, or the file when
    there is no Hub); `pending` is what this server added since. A Hub save writes the Hub's own total + pending,
    so a second copy of the app saving at the same time (as happens during a deploy) loses nothing."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.base = dict.fromkeys(COUNTERS, 0)
        self.pending = dict.fromkeys(COUNTERS, 0)
        self.since = clock()                                   # when counting started
        self.tabs: Dict[str, Tuple[str, float]] = {}           # tab id -> (visitor id, last heartbeat)
        self.new_by_ip: Dict[str, int] = {}
        self.ip_day = self._day()
        self.version = 0                                       # bumped on every change, so the savers know

    def _day(self) -> int:
        return int(self.clock() // 86400)

    def _add(self, key: str, n: int) -> None:                 # call with the lock held
        self.pending[key] += n
        self.version += 1

    # ------------------------------------------------------------------ events
    def record_review(self, plies: int) -> None:
        with self.lock:
            self._add("games", 1)
            self._add("moves", max(0, int(plies)))

    def record_move(self) -> None:
        with self.lock:
            self._add("moves", 1)

    def heartbeat(self, visitor: str, tab: str, first: bool = False, ip: str = "") -> bool:
        """A tab is open and visible. `first` asks to count this browser as a new user.
        Returns True if the browser is now counted (it then stops asking)."""
        now = self.clock()
        with self.lock:
            self._prune(now)
            if tab in self.tabs or len(self.tabs) < MAX_TABS:
                self.tabs[tab] = (visitor, now)
            if not first:
                return True
            day = self._day()
            if day != self.ip_day:
                self.new_by_ip, self.ip_day = {}, day
            if self.new_by_ip.get(ip, 0) >= NEW_USERS_PER_IP:
                return False
            self.new_by_ip[ip] = self.new_by_ip.get(ip, 0) + 1
            self._add("users", 1)
            return True

    def leave(self, tab: str) -> None:
        with self.lock:
            self.tabs.pop(tab, None)

    def _prune(self, now: float) -> None:
        cutoff = now - ONLINE_WINDOW
        for tab in [t for t, (_, seen) in self.tabs.items() if seen < cutoff]:
            del self.tabs[tab]

    # ------------------------------------------------------------------ reading
    def totals(self) -> dict:
        with self.lock:
            return {**{k: self.base[k] + self.pending[k] for k in COUNTERS}, "since": int(self.since)}

    def snapshot(self) -> dict:
        """What the front page shows."""
        totals = self.totals()
        with self.lock:
            self._prune(self.clock())
            totals["online"] = len({visitor for visitor, _ in self.tabs.values()})
        return totals

    # ------------------------------------------------------------------ saving
    def to_file(self) -> dict:
        """The local file keeps the totals and, separately, what has not reached the Hub yet."""
        with self.lock:
            pending = dict(self.pending)
        return {**self.totals(), "pending": pending}

    def restore_file(self, data: object) -> None:
        """Start from the local file written before a restart."""
        if not isinstance(data, dict):
            return
        total, pending = _counts(data), _counts(data.get("pending"))
        with self.lock:
            for k in COUNTERS:
                self.base[k] = max(self.base[k], total[k] - pending[k])
                self.pending[k] += pending[k]
            self._adopt_since(data.get("since"))
            self.version += 1

    def adopt(self, remote: object) -> bool:
        """Take the Hub's totals as the base. Returns True if the Hub lacks something we know, so it needs a save."""
        counts = _counts(remote)
        with self.lock:
            behind = not isinstance(remote, dict)
            for k in COUNTERS:
                if self.base[k] > counts[k]:
                    behind = True                              # the Hub copy is older than ours (or was reset)
                elif counts[k] > self.base[k]:
                    self.base[k] = counts[k]
                    self.version += 1
            since = remote.get("since") if isinstance(remote, dict) else None
            if not isinstance(since, (int, float)) or int(since) > int(self.since):
                behind = True
            self._adopt_since(since)
            return behind or any(self.pending.values())

    def saved(self, sent_pending: Dict[str, int], sent_totals: dict) -> None:
        """`sent_totals` (which included `sent_pending`) were written to the Hub: they become the base."""
        with self.lock:
            for k in COUNTERS:
                self.base[k] = sent_totals[k]
                self.pending[k] -= sent_pending[k]
            self.version += 1

    def _adopt_since(self, since: object) -> None:             # call with the lock held
        if isinstance(since, (int, float)) and 0 < since < self.since:
            self.since = since


# ---------------------------------------------------------------------- storage
def default_file() -> Path:
    if os.environ.get("STATS_FILE"):
        return Path(os.environ["STATS_FILE"])
    data = Path("/data")
    if data.is_dir() and os.access(data, os.W_OK):
        return data / "movelens-stats.json"
    return Path(tempfile.gettempdir()) / "movelens-stats.json"


def read_file(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)                                      # atomic: a crash never leaves half a file


class HubStore:
    """The totals as stats.json in a private Hugging Face dataset."""
    FILE = "stats.json"

    def __init__(self, repo: str, token: str):
        from huggingface_hub import HfApi                     # only needed when syncing is switched on
        self.repo, self.token = repo, token
        self.api = HfApi(token=token)
        self.created = False

    def load(self) -> Optional[dict]:
        """The saved totals, or None if there are none yet. Raises if the Hub can't be reached."""
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError
        try:
            path = hf_hub_download(self.repo, self.FILE, repo_type="dataset", token=self.token,
                                   cache_dir=Path(tempfile.gettempdir()) / "movelens-hub")
        except (EntryNotFoundError, RepositoryNotFoundError):
            # Make sure before saying "nothing saved yet": that answer lets the next save start from zero.
            if self.api.file_exists(self.repo, self.FILE, repo_type="dataset"):
                raise ConnectionError("the Hub said stats.json is missing, but it exists") from None
            return None
        data = read_file(Path(path))
        if data is None:
            raise ValueError("stats.json on the Hub could not be read")
        return data

    def save(self, data: dict) -> None:
        if not self.created:                       # a token limited to this one dataset may not create repositories
            if not self.api.repo_exists(self.repo, repo_type="dataset"):
                self.api.create_repo(self.repo, repo_type="dataset", private=True, exist_ok=True)
            self.created = True
        self.api.upload_file(path_or_fileobj=json.dumps(data, indent=1).encode(), path_in_repo=self.FILE,
                             repo_id=self.repo, repo_type="dataset", commit_message="Update MoveLens usage totals")


def hub_from_env() -> Optional[HubStore]:
    token = os.environ.get("HF_TOKEN", "").strip()
    repo = os.environ.get("STATS_REPO", "").strip()
    if not repo and os.environ.get("SPACE_AUTHOR_NAME"):      # running inside a Hugging Face Space
        repo = f"{os.environ['SPACE_AUTHOR_NAME']}/movelens-stats"
    if not (token and repo):
        return None
    try:
        return HubStore(repo, token)
    except ImportError:
        print("[movelens] HF_TOKEN is set but huggingface_hub is not installed; usage totals stay local.", flush=True)
        return None


class Keeper:
    """Saves the totals in the background: to the local file every half minute and to the Hub every ten minutes,
    each only when something changed. Every Hub save reads the Hub first and adds to it, and nothing is written
    while it can't be read, so a network problem can never replace the real totals with smaller ones."""

    def __init__(self, stats: Stats, path: Optional[Path], hub: Optional[HubStore]):
        self.stats, self.path, self.hub = stats, path, hub
        self.saved_version = -1
        self.hub_loaded = False
        self.last_sync = 0.0
        self.sync_lock = threading.Lock()
        self.stop = threading.Event()

    def describe(self) -> dict:
        """Where the totals are kept, for /api/health."""
        return {"file": bool(self.path), "hub": self.hub.repo if self.hub else None, "hub_ok": self.hub_loaded}

    def start(self) -> None:
        if self.path:
            self.stats.restore_file(read_file(self.path))
        self.sync()
        threading.Thread(target=self._loop, name="stats-keeper", daemon=True).start()

    def _loop(self) -> None:
        while not self.stop.wait(SAVE_EVERY):
            wait = SYNC_EVERY if self.hub_loaded else 2 * SAVE_EVERY      # retry a failed first read sooner
            due = bool(self.hub) and time.time() - self.last_sync >= wait
            self.flush(sync=due)

    def flush(self, sync: bool = True) -> None:
        if sync:
            self.sync()
        self.save_file()

    def save_file(self) -> None:
        version = self.stats.version
        if not self.path or version == self.saved_version:
            return
        try:
            write_file(self.path, self.stats.to_file())
            self.saved_version = version
        except OSError as e:
            print(f"[movelens] Could not save usage totals to {self.path}: {e}", flush=True)
            self.path = None

    def sync(self) -> None:
        if not self.hub:
            return
        with self.sync_lock:
            self.last_sync = time.time()
            with self.stats.lock:
                sending = dict(self.stats.pending)
            try:
                remote = self.hub.load()
            except Exception as e:  # noqa: BLE001 - keep serving; try again next round
                print(f"[movelens] Could not read usage totals from {self.hub.repo}: {e}", flush=True)
                return
            self.hub_loaded = True
            if not self.stats.adopt(remote):
                return                                         # the Hub already has everything
            with self.stats.lock:
                totals = {**{k: self.stats.base[k] + sending[k] for k in COUNTERS}, "since": int(self.stats.since)}
            try:
                self.hub.save(totals)
            except Exception as e:  # noqa: BLE001
                print(f"[movelens] Could not save usage totals to {self.hub.repo}: {e}", flush=True)
                return
            self.stats.saved(sending, totals)
        self.save_file()                                       # so a restart can't count the same moves twice
