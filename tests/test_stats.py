"""The public numbers: counting, the online window, abuse limits, and saving without ever losing the totals."""
import json

import app.stats as stats_mod
from app.stats import Keeper, Stats, valid_id


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_reviews_and_board_moves_are_counted():
    s = Stats()
    s.record_review(80)
    s.record_review(41)
    s.record_move()
    snap = s.snapshot()
    assert (snap["games"], snap["moves"]) == (2, 122)


def test_online_counts_browsers_not_tabs_and_forgets_silent_tabs():
    clock = Clock()
    s = Stats(clock)
    s.heartbeat("visitor-aaaa", "tab-1111")
    s.heartbeat("visitor-aaaa", "tab-2222")             # same browser, second tab
    s.heartbeat("visitor-bbbb", "tab-3333")
    assert s.snapshot()["online"] == 2
    s.leave("tab-3333")
    assert s.snapshot()["online"] == 1
    clock.t += stats_mod.ONLINE_WINDOW + 1               # no heartbeat for too long
    assert s.snapshot()["online"] == 0


def test_a_browser_is_counted_as_a_user_once_it_asks():
    s = Stats(Clock())
    assert s.heartbeat("visitor-aaaa", "tab-1111", first=True, ip="1.2.3.4")
    s.heartbeat("visitor-aaaa", "tab-1111", first=False, ip="1.2.3.4")
    assert s.snapshot()["users"] == 1


def test_one_address_cannot_inflate_the_user_count(monkeypatch):
    monkeypatch.setattr(stats_mod, "NEW_USERS_PER_IP", 3)
    clock = Clock()
    s = Stats(clock)
    answers = [s.heartbeat(f"visitor-{i:04}", f"tab-{i:06}", first=True, ip="9.9.9.9") for i in range(5)]
    assert answers == [True, True, True, False, False]
    assert s.heartbeat("visitor-other", "tab-other1", first=True, ip="8.8.8.8")   # other addresses are unaffected
    clock.t += 86400                                                             # a new day resets the limit
    assert s.heartbeat("visitor-late", "tab-late01", first=True, ip="9.9.9.9")
    assert s.snapshot()["users"] == 5


def test_ids_are_validated():
    assert valid_id("Ab3_-xyz") and not valid_id("short") and not valid_id("has space here") and not valid_id(None)


def test_saved_totals_become_the_base_and_what_was_added_meanwhile_is_kept():
    s = Stats(Clock(2_000_000_000.0))
    s.record_review(10)                                  # counted here before the saved totals were read
    assert s.adopt({"games": 5, "moves": 3, "users": 7, "since": 1_900_000_000}) is True   # ours must be saved
    assert s.totals() == {"games": 6, "moves": 13, "users": 7, "since": 1_900_000_000}
    s.adopt({"games": "lots", "moves": None})            # junk never lowers the totals
    s.adopt(None)
    assert s.totals()["games"] == 6


def test_totals_survive_a_restart_through_the_file(tmp_path):
    path = tmp_path / "stats.json"
    first = Stats()
    keeper = Keeper(first, path, None)
    keeper.start()
    first.record_review(30)
    keeper.flush()
    assert json.loads(path.read_text())["games"] == 1

    second = Stats()
    Keeper(second, path, None).start()
    assert second.totals()["moves"] == 30


class FakeHub:
    repo = "someone/movelens-stats"

    def __init__(self, saved=None, fail_reads=0):
        self.saved, self.fail_reads, self.writes = saved, fail_reads, 0

    def load(self):
        if self.fail_reads:
            self.fail_reads -= 1
            raise ConnectionError("hub unreachable")
        return self.saved

    def save(self, data):
        self.saved, self.writes = dict(data), self.writes + 1


def test_hub_totals_are_restored_and_updated():
    hub = FakeHub({"games": 100, "moves": 5000, "users": 40, "since": 1_700_000_000})
    s = Stats()
    keeper = Keeper(s, None, hub)
    keeper.start()
    assert s.totals()["games"] == 100
    keeper.flush()
    assert hub.writes == 0                               # nothing new: no needless commit
    s.record_review(20)
    keeper.flush()
    assert hub.saved["games"] == 101 and hub.saved["moves"] == 5020 and hub.writes == 1


def test_hub_is_never_overwritten_before_it_could_be_read():
    hub = FakeHub({"games": 100, "moves": 5000, "users": 40, "since": 1_700_000_000}, fail_reads=1)
    s = Stats()
    keeper = Keeper(s, None, hub)
    keeper.start()                                       # the read fails: we know nothing about the real totals
    s.record_review(10)
    assert hub.saved["games"] == 100
    keeper.flush()                                       # read works now: merge first, then save
    assert hub.saved["games"] == 101 and hub.saved["moves"] == 5010


def test_saving_merges_what_another_copy_of_the_app_wrote():
    hub = FakeHub({"games": 10, "moves": 100, "users": 5, "since": 1_700_000_000})
    s = Stats()
    keeper = Keeper(s, None, hub)
    keeper.start()
    hub.saved = {**hub.saved, "users": 9}                # e.g. the old container saved once more during a deploy
    s.record_move()
    keeper.flush()
    assert hub.saved["users"] == 9 and hub.saved["moves"] == 101


def test_a_restart_after_a_hub_save_does_not_count_twice(tmp_path):
    path, hub = tmp_path / "stats.json", FakeHub()
    s = Stats()
    keeper = Keeper(s, path, hub)
    keeper.start()
    s.record_review(40)
    keeper.flush()                                       # saved to the Hub, and the file records nothing is pending
    assert hub.saved["games"] == 1
    writes = hub.writes

    again = Stats()
    keeper2 = Keeper(again, path, hub)
    keeper2.start()
    keeper2.flush()
    assert again.totals()["games"] == 1 and hub.saved["games"] == 1
    assert hub.writes == writes                          # nothing new to say: no commit
