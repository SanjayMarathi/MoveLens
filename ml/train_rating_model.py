"""
Step 2 of training: learn rating = f(features) and save the model for the web app.

    python -m ml.train_rating_model ml/dataset.csv

Model: gradient-boosted decision trees (scikit-learn's HistGradientBoostingRegressor). They work
very well on small tabular feature sets like ours and need no feature scaling.

It prints the test error next to a "guess the average rating" baseline, so you can tell
whether the model actually learned something.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.features import FEATURE_NAMES

MODEL_PATH = Path(__file__).resolve().parent / "rating_model.joblib"


def load(path):
    X, y = [], []
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[:-1] != FEATURE_NAMES:
            raise SystemExit("CSV columns don't match app/features.py; rebuild the dataset.")
        for row in reader:
            X.append([float(v) for v in row[:-1]])
            y.append(float(row[-1]))
    return X, y


def main(argv=None):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import train_test_split

    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default=str(MODEL_PATH))
    args = ap.parse_args(argv)

    X, y = load(args.csv)
    if len(X) < 50:
        raise SystemExit(f"Only {len(X)} rows: collect more games first.")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, early_stopping=True,
                                          random_state=42)
    model.fit(X_train, y_train)

    mae = mean_absolute_error(y_test, model.predict(X_test))
    mean_rating = sum(y_train) / len(y_train)
    baseline = mean_absolute_error(y_test, [mean_rating] * len(y_test))
    print(f"Rows: {len(X)}  |  test MAE: {mae:.0f} rating points  "
          f"(baseline that always guesses {mean_rating:.0f}: {baseline:.0f})")

    joblib.dump({"model": model, "features": FEATURE_NAMES, "mae": mae}, args.out)
    print(f"Saved {args.out}; restart the server to show 'Estimated rating' in reviews.")


if __name__ == "__main__":
    main()
