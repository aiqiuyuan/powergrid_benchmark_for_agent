"""Frozen-training Trading baselines; no target labels or online model updates.

Competition-inspired variants are adaptations to the restricted feature table,
not reproductions of the submitted SVK/GEB models or competition Benchmark.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import pickle
import sys

import numpy as np

METHODS = ("ridge-generation", "ridge-spread", "hgb-generation", "hgb-direct",
           "geb-quantile-adapted", "svk-catboost-adapted", "organizer-spline-adapted")
QUANTILES = (.1, .3, .5, .7, .9)


def expected_bid(generation, da_minus_ss):
    """Maximize expected quadratic settlement, then apply the bid bounds."""
    return np.clip(np.asarray(generation) + np.asarray(da_minus_ss) / .14, 0, 1800)


def quantile_mean(predictions):
    """Fixed midpoint quadrature, including explicit constant tail approximation."""
    return np.mean(predictions, axis=1)


def check_alignment(features, labels):
    if not features or [r["timestamp"] for r in features] != [r["timestamp"] for r in labels]:
        raise ValueError("Nonempty timestamp-aligned training data required")


def nonlinear(x, columns):
    parts = [np.ones((len(x), 1)), x]
    for key in ("wind_wind_speed", "wind_wind_speed_100", "solar_solar_down_radiation"):
        if key in columns:
            z = x[:, columns.index(key):columns.index(key) + 1]
            parts += [z * z, z * z * z]
    return np.concatenate(parts, axis=1)


def train(data: Path, output: Path, method: str, seed: int):
    if method not in METHODS:
        raise ValueError("Unknown fixed method")
    with (data / "train_features.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    with (data / "train_labels.csv").open() as stream:
        labels = list(csv.DictReader(stream))
    check_alignment(rows, labels)
    columns = [k for k in rows[0] if k != "timestamp"]
    x = np.array([[float(r[k]) for k in columns] for r in rows])
    y = np.array([float(r["total_generation_mwh"]) for r in labels])
    spread = np.array([float(r["da_price"]) - float(r["ss_price"]) for r in labels])
    model = {"method": method, "columns": columns, "seed": seed}
    if method.startswith("ridge"):
        z = nonlinear(x, columns)
        mean, scale = z.mean(0), z.std(0)
        mean[0] = 0
        scale[scale < 1e-8] = 1
        z = (z - mean) / scale
        penalty = np.eye(z.shape[1]) * 100.
        penalty[0, 0] = 1e-6
        # Unclipped conditional means correspond to the quadratic revenue objective.
        coef = np.linalg.solve(z.T @ z + penalty, z.T @ np.column_stack((y, spread)))
        model.update(mean=mean, scale=scale, coef=coef)
    elif method == "svk-catboost-adapted":
        from catboost import CatBoostRegressor
        estimator = CatBoostRegressor(iterations=600, depth=6, learning_rate=.05,
                                      loss_function="RMSE", random_seed=seed,
                                      thread_count=1, verbose=False, allow_writing_files=False)
        # A single-stage direct optimal-bid learner; not SVK's unavailable forecast stack.
        estimator.fit(x, y + spread / .14)
        model["estimators"] = [estimator]
    elif method == "organizer-spline-adapted":
        from sklearn.compose import ColumnTransformer
        from sklearn.linear_model import QuantileRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import SplineTransformer
        # Organizer notebook uses df=5 solar and df=8 wind cubic B-splines.
        # sklearn's constant extrapolation differs from patsy's out-of-range rejection.
        transformer = ColumnTransformer([
            ("solar", SplineTransformer(n_knots=4, degree=3, knots="quantile", include_bias=False),
             [columns.index("solar_solar_down_radiation")]),
            ("wind", SplineTransformer(n_knots=7, degree=3, knots="quantile", include_bias=False),
             [columns.index("wind_wind_speed_100")]),
        ])
        estimator = make_pipeline(transformer, QuantileRegressor(quantile=.5, alpha=0., solver="highs"))
        estimator.fit(x, y)
        model["estimators"] = [estimator]
    else:
        from sklearn.ensemble import HistGradientBoostingRegressor
        options = dict(max_iter=200, max_leaf_nodes=31, learning_rate=.1,
                       early_stopping=False, l2_regularization=1., random_state=seed)
        generation = HistGradientBoostingRegressor(**options).fit(x, y)
        estimators = [generation]
        if method == "hgb-direct":
            estimators = [HistGradientBoostingRegressor(**options).fit(x, y + spread / .14)]
        elif method == "geb-quantile-adapted":
            # GEB-inspired price-spread distribution plus an expected-revenue decision.
            # Midpoint quadrature and HGB choices are disclosed implementation assumptions.
            estimators += [HistGradientBoostingRegressor(loss="quantile", quantile=q, **options)
                           .fit(x, spread) for q in QUANTILES]
        model["estimators"] = estimators
    with (output / "model.pkl").open("wb") as stream:
        pickle.dump(model, stream, protocol=4)


def predict(model_path: Path, request: Path, output: Path):
    # Artifacts are generated by this fixed training program in the isolated scorer.
    with (model_path / "model.pkl").open("rb") as stream:
        model = pickle.load(stream)
    day = json.loads(request.read_text())
    x = np.array([[float(r[k]) for k in model["columns"]] for r in day["periods"]])
    method = model["method"]
    if method.startswith("ridge"):
        z = (nonlinear(x, model["columns"]) - model["mean"]) / model["scale"]
        means = z @ model["coef"]
        values = expected_bid(means[:, 0], means[:, 1] if method == "ridge-spread" else 0.)
    else:
        estimators = model["estimators"]
        generation = estimators[0].predict(x)
        spread = (quantile_mean(np.column_stack([e.predict(x) for e in estimators[1:]]))
                  if method == "geb-quantile-adapted" else 0.)
        values = expected_bid(generation, spread)
    if not np.all(np.isfinite(values)):
        raise ValueError("Nonfinite bids")
    (output / "bids.json").write_text(json.dumps({"bids": [
        {"timestamp": row["timestamp"], "bid_mwh": float(value)}
        for row, value in zip(day["periods"], values)]}, allow_nan=False))


if __name__ == "__main__":
    if sys.argv[1] == "train":
        method = (Path(__file__).parent / "method.txt").read_text().strip()
        train(Path(sys.argv[2]), Path(sys.argv[3]), method, int(sys.argv[4]))
    elif sys.argv[1] == "predict":
        predict(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        raise ValueError("Use train or predict")
