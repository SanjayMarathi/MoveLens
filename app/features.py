"""
Features for the (optional) machine-learning rating estimator.

The model learns "how strong was this player in this game?" from how much win% they lost on each
move. We use only per-move win% losses so that features are computed the SAME way from:
  * our own reviews (Stockfish analysis), when serving, and
  * Lichess database games that already contain "[%eval ...]" comments, when training.
Training/serving consistency matters more than clever features.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from .classify import move_accuracy

FEATURE_NAMES = [
    "moves", "mean_loss", "mean_accuracy", "max_loss",
    "frac_lt1", "frac_lt2", "frac_lt5", "frac_lt10", "frac_lt20", "frac_ge20",
    "time_base", "time_increment",
]


def parse_time_control(tc: Optional[str]):
    """'600+5' -> (600, 5). Unknown/correspondence -> (-1, -1)."""
    try:
        base, inc = (tc or "").split("+")
        return float(base), float(inc)
    except ValueError:
        return -1.0, -1.0


def player_features(losses: Sequence[float], time_control: Optional[str] = None) -> Optional[List[float]]:
    """`losses`: win% lost on each of one player's moves (book and forced moves excluded)."""
    n = len(losses)
    if n < 5:
        return None   # too few moves to say anything
    frac = lambda cond: sum(1 for x in losses if cond(x)) / n  # noqa: E731
    base, inc = parse_time_control(time_control)
    return [
        float(n),
        sum(losses) / n,
        sum(move_accuracy(x) for x in losses) / n,
        max(losses),
        frac(lambda x: x < 1), frac(lambda x: x < 2), frac(lambda x: x < 5),
        frac(lambda x: x < 10), frac(lambda x: x < 20), frac(lambda x: x >= 20),
        base, inc,
    ]


class RatingModel:
    """Loads ml/rating_model.joblib if it exists; otherwise estimates are simply not shown."""

    def __init__(self, path):
        self.model = None
        try:
            import joblib  # comes with scikit-learn
            if path.exists():
                bundle = joblib.load(path)
                if bundle.get("features") == FEATURE_NAMES:
                    self.model = bundle["model"]
        except Exception:
            self.model = None

    @property
    def available(self) -> bool:
        return self.model is not None

    def predict(self, features: Optional[List[float]]) -> Optional[int]:
        if not self.available or features is None:
            return None
        return int(round(float(self.model.predict([features])[0]) / 50) * 50)  # round to 50
