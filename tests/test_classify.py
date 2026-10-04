import pytest

from app.chess_core import Board, parse_san
from app.classify import (MoveFacts, Score, classify, find_sacrifice, game_accuracy, move_accuracy,
                          win_percent_cp)


def facts(**kw):
    base = dict(win_before=50, win_after=50, is_best=False, second_best_win=None, legal_move_count=30,
                in_check=False, is_book=False, is_recapture=False, sacrifice=0, is_promotion=False,
                previous_label=None)
    base.update(kw)
    return MoveFacts(**base)


def test_win_percent_curve():
    assert win_percent_cp(0) == pytest.approx(50)
    assert 55 < win_percent_cp(100) < 60           # +1 pawn ~ 59%
    assert win_percent_cp(1000) > 97
    assert win_percent_cp(-300) == pytest.approx(100 - win_percent_cp(300))


def test_score_point_of_view_and_text():
    assert Score(cp=150).text() == "+1.50"
    assert Score(mate=-2).text() == "-M2"
    assert Score(mate=3).win_for("b") == 0
    assert Score(result="1-0").win_for("w") == 100
    assert Score(result="1/2-1/2").win_white() == 50


@pytest.mark.parametrize("loss, label", [
    (1.5, "excellent"), (3, "good"), (7, "inaccuracy"), (15, "mistake"), (35, "blunder"),
])
def test_loss_thresholds(loss, label):
    assert classify(facts(win_before=60, win_after=60 - loss)) == label


def test_best_book_forced():
    assert classify(facts(is_best=True)) == "best"
    assert classify(facts(is_book=True, win_after=0)) == "book"
    assert classify(facts(legal_move_count=1, win_after=0)) == "forced"


def test_great_is_the_only_good_move():
    assert classify(facts(is_best=True, win_before=70, second_best_win=40)) == "great"
    # not great if the alternatives were also fine, or it's just a recapture
    assert classify(facts(is_best=True, win_before=70, second_best_win=66)) == "best"
    assert classify(facts(is_best=True, win_before=70, second_best_win=40, is_recapture=True)) == "best"


def test_brilliant_needs_a_sound_sacrifice():
    assert classify(facts(is_best=True, sacrifice=3, win_before=60, win_after=60)) == "brilliant"
    assert classify(facts(is_best=True, sacrifice=3, win_before=99, win_after=99)) == "best"  # already won
    assert classify(facts(is_best=False, sacrifice=3, win_before=60, win_after=40)) != "brilliant"


def test_miss_after_opponent_mistake():
    f = facts(win_before=85, win_after=70, previous_label="blunder")
    assert classify(f) == "miss"


def test_move_accuracy_curve():
    assert move_accuracy(0) == pytest.approx(100, abs=0.01)
    assert 60 < move_accuracy(10) < 70
    assert move_accuracy(80) < 1


def test_game_accuracy_punishes_a_blunder():
    wins = [50] * 21
    perfect = game_accuracy(wins, [100.0] * 20, ["w", "b"] * 10, "w")
    one_blunder = game_accuracy(wins, [100.0] * 18 + [5.0, 100.0], ["w", "b"] * 10, "w")
    assert perfect > 99 and one_blunder < 80


def play(fen, *sans):
    b = Board(fen)
    for s in sans:
        b.push(parse_san(b, s))
    return b


def test_sacrifice_detection():
    # Greek gift: Bxh7+ gives up the bishop for a pawn
    fen = "r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R2QK2R w KQ - 0 1"
    after = play(fen, "Bxh7+")
    assert find_sacrifice(after, "w", captured_value=1) == 2
    # A normal developing move sacrifices nothing
    assert find_sacrifice(play(fen, "a3"), "w", 0) <= 0
    # A queen trade is not a sacrifice
    trade = Board("3qk3/8/8/8/8/8/8/3QK3 w - - 0 1")
    assert find_sacrifice(play(trade.fen(), "Qxd8+"), "w", captured_value=9) < 2
