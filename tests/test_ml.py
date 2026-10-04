import csv
import random

import pytest

from app.features import FEATURE_NAMES, RatingModel, player_features
from ml import build_dataset

LICHESS_GAME = """[Event "Rated Blitz game"]
[White "a"]
[Black "b"]
[WhiteElo "1800"]
[BlackElo "1750"]
[TimeControl "180+2"]

1. e4 { [%eval 0.2] } 1... e5 { [%eval 0.2] } 2. Nf3 { [%eval 0.2] } 2... Nc6 { [%eval 0.3] }
3. Bc4 { [%eval 0.25] } 3... Nf6 { [%eval 0.3] } 4. d3 { [%eval 0.1] } 4... h6 { [%eval 0.5] }
5. O-O { [%eval 0.4] } 5... d6 { [%eval 0.5] } 6. c3 { [%eval 0.4] } 6... Be7 { [%eval 0.5] }
7. Re1 { [%eval 0.4] } 7... O-O { [%eval 0.4] } 8. h3 { [%eval 0.3] } 8... a6 { [%eval 0.3] }
9. a4 { [%eval 0.3] } 9... Nh7 { [%eval 1.5] } 10. d4 { [%eval 1.2] } 10... Ng5 { [%eval 4.0] }
11. Nxg5 { [%eval 3.9] } 11... hxg5 { [%eval 4.2] } 12. Qh5 { [%eval 3.0] } 1-0
"""


def test_features_shape():
    assert player_features([1.0] * 4) is None
    f = player_features([0, 0, 3, 12, 25, 0.5], "300+2")
    assert len(f) == len(FEATURE_NAMES) and f[0] == 6 and f[-2:] == [300.0, 2.0]


def test_build_dataset_from_lichess_evals(tmp_path):
    pgn = tmp_path / "games.pgn"
    pgn.write_text(LICHESS_GAME + "\n" + LICHESS_GAME.replace("1800", "1200"))
    out = tmp_path / "data.csv"
    build_dataset.main([str(pgn), str(out)])
    rows = list(csv.reader(out.open()))
    assert rows[0] == FEATURE_NAMES + ["rating"]
    assert len(rows) == 5                              # header + 2 games x 2 players
    assert {r[-1] for r in rows[1:]} == {"1800", "1750", "1200"}


def test_train_and_load_model(tmp_path):
    pytest.importorskip("sklearn")
    from ml import train_rating_model
    rnd = random.Random(0)
    path = tmp_path / "data.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FEATURE_NAMES + ["rating"])
        for _ in range(400):                           # synthetic: stronger players lose less win%
            rating = rnd.randint(800, 2400)
            losses = [max(0, rnd.gauss((2600 - rating) / 200, 3)) for _ in range(30)]
            w.writerow(player_features(losses, "300+0") + [rating])
    model_path = tmp_path / "model.joblib"
    train_rating_model.main([str(path), "--out", str(model_path)])
    model = RatingModel(model_path)
    assert model.available
    strong = model.predict(player_features([0.2] * 30, "300+0"))
    weak = model.predict(player_features([12.0] * 30, "300+0"))
    assert strong > weak
