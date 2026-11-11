"""Train the demand-forecast model and produce planning outputs.

- Features per material-plant-week: lag 1/4/12 weeks, rolling mean 4/12,
  calendar month, plant + material one-hots.
- Model: RandomForestRegressor (n_estimators=200).
- Time-based split: last 12 weeks are the test set, everything before is train.
- Outputs:
    results/metrics.json          (MAE, RMSE, MAPE, R2 on the test set)
    models/demand_forecast.joblib (trained model)
    docs/forecast_vs_actual.png   (test-set chart)
    docs/abc_pareto.png           (ABC Pareto chart)
    data/inventory.db             (forecasts + reorder_recommendations tables)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "inventory.db"
MODELS_DIR = ROOT / "models"
RESULTS_DIR = ROOT / "results"
DOCS_DIR = ROOT / "docs"
TEST_WEEKS = 12
MODEL_NAME = "RandomForestRegressor(n_estimators=200, max_depth=12)"


def build_features(cons: pd.DataFrame) -> pd.DataFrame:
    """Add lag / rolling / calendar features per material-plant series."""
    cons = cons.sort_values(["material_id", "plant_id", "week_number"]).copy()
    g = cons.groupby(["material_id", "plant_id"])["consumption_qty"]
    cons["lag_1"] = g.shift(1)
    cons["lag_4"] = g.shift(4)
    cons["lag_12"] = g.shift(12)
    cons["roll_mean_4"] = g.transform(lambda s: s.shift(1).rolling(4).mean())
    cons["roll_mean_12"] = g.transform(lambda s: s.shift(1).rolling(12).mean())
    cons["week_start"] = pd.to_datetime(cons["week_start"])
    cons["month"] = cons["week_start"].dt.month
    cons["week_of_year"] = cons["week_start"].dt.isocalendar().week.astype(int)
    return cons.dropna(subset=["lag_1", "lag_4", "lag_12", "roll_mean_4", "roll_mean_12"])


def encode(df: pd.DataFrame, columns: list[str] | None = None):
    """One-hot encode plant + material; return (X, feature_names)."""
    X = pd.get_dummies(df, columns=["plant_id", "material_id"], dtype=float)
    if columns is not None:
        X = X.reindex(columns=columns, fill_value=0.0)
    return X


def compute_reorder(df: pd.DataFrame, materials: pd.DataFrame,
                    snapshot: pd.DataFrame, abc: pd.DataFrame) -> pd.DataFrame:
    """Safety stock + reorder point + stockout-risk flag per material-plant.

    safety_stock = z * sigma_demand * sqrt(lead_time_weeks)
    reorder_point = avg_weekly_demand * lead_time_weeks + safety_stock
    """
    mat = materials.set_index("material_id")
    abc_map = abc.set_index("material_id")["abc_class"].to_dict()
    snap = snapshot.set_index(["material_id", "plant_id"])["on_hand_qty"].to_dict()
    rows = []
    today = pd.Timestamp("2025-12-29").date().isoformat()  # last week in the data
    for (material_id, plant_id), grp in df.groupby(["material_id", "plant_id"]):
        avg_d = grp["consumption_qty"].mean()
        std_d = grp["consumption_qty"].std(ddof=1) or 0.0
        lt = int(mat.loc[material_id, "lead_time_weeks"])
        z = float(mat.loc[material_id, "safety_factor"])
        safety = z * std_d * np.sqrt(lt)
        rop = avg_d * lt + safety
        on_hand = int(snap.get((material_id, plant_id), 0))
        if on_hand <= rop * 0.5:
            risk = "HIGH"
        elif on_hand <= rop:
            risk = "MEDIUM"
        else:
            risk = "LOW"
        rows.append(
            {
                "material_id": material_id,
                "plant_id": plant_id,
                "avg_weekly_demand": round(avg_d, 2),
                "demand_std": round(std_d, 2),
                "safety_stock": round(safety, 2),
                "reorder_point": round(rop, 2),
                "on_hand_qty": on_hand,
                "recommended_order_qty": round(max(0.0, rop * 2 - on_hand), 2),
                "stockout_risk": risk,
                "abc_class": abc_map.get(material_id, "C"),
                "generated_date": today,
            }
        )
    return pd.DataFrame(rows)


def abc_analysis(cons: pd.DataFrame, materials: pd.DataFrame) -> pd.DataFrame:
    cost = materials.set_index("material_id")["unit_cost_inr"]
    yearly = (
        cons.assign(value=cons["material_id"].map(cost) * cons["consumption_qty"])
        .groupby("material_id")["value"]
        .sum()
        .sort_values(ascending=False)
    )
    total = yearly.sum()
    cum = yearly.cumsum() / total
    cls = np.where(cum <= 0.80, "A", np.where(cum <= 0.95, "B", "C"))
    return pd.DataFrame(
        {
            "material_id": yearly.index,
            "annual_value_inr": yearly.values.round(2),
            "cum_pct": (cum.values * 100).round(2),
            "abc_class": cls,
        }
    )


def plot_forecast_vs_actual(test: pd.DataFrame, path: Path) -> None:
    agg = (
        test.groupby("week_start")[["actual_qty", "forecast_qty"]]
        .sum()
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(agg["week_start"], agg["actual_qty"], marker="o", label="Actual")
    ax.plot(agg["week_start"], agg["forecast_qty"], marker="s", label="Forecast")
    ax.set_title("Forecast vs Actual — total weekly consumption (test set, last 12 weeks)")
    ax.set_xlabel("Week")
    ax.set_ylabel("Units consumed")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_abc_pareto(abc: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    vals = abc["annual_value_inr"].values
    ax.bar(range(len(vals)), vals, color="#4C72B0")
    ax2 = ax.twinx()
    ax2.plot(range(len(vals)), abc["cum_pct"].values, color="#C44E52", marker="o")
    ax2.axhline(80, color="#C44E52", linestyle="--", linewidth=1)
    ax2.axhline(95, color="#C44E52", linestyle=":", linewidth=1)
    ax2.set_ylabel("Cumulative % of value")
    ax.set_xlabel("Materials (ranked by annual consumption value)")
    ax.set_ylabel("Annual consumption value (INR)")
    ax.set_title("ABC Pareto — a few materials drive most of the spend")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    cons = pd.read_csv(DATA_DIR / "consumption_history.csv")
    materials = pd.read_csv(DATA_DIR / "materials.csv")
    snapshot = pd.read_csv(DATA_DIR / "inventory_snapshot.csv")
    feat = build_features(cons)

    feature_cols = ["lag_1", "lag_4", "lag_12", "roll_mean_4", "roll_mean_12",
                    "month", "week_of_year"]
    max_week = feat["week_number"].max()
    train_df = feat[feat["week_number"] <= max_week - TEST_WEEKS]
    test_df = feat[feat["week_number"] > max_week - TEST_WEEKS]

    X_train = encode(train_df[feature_cols + ["plant_id", "material_id"]])
    X_test = encode(test_df[feature_cols + ["plant_id", "material_id"]],
                    columns=list(X_train.columns))
    y_train = train_df["consumption_qty"]
    y_test = test_df["consumption_qty"]

    model = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1,
                                  max_depth=12, min_samples_leaf=2)
    model.fit(X_train, y_train)
    pred = np.maximum(0, model.predict(X_test))

    mae = float(mean_absolute_error(y_test, pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mape = float(np.mean(np.abs(y_test - pred) / np.maximum(y_test, 1)) * 100)
    r2 = float(r2_score(y_test, pred))
    metrics = {
        "model": MODEL_NAME,
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "test_weeks": TEST_WEEKS,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "mape_pct": round(mape, 2),
        "r2": round(r2, 3),
    }
    (RESULTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    joblib.dump(model, MODELS_DIR / "demand_forecast.joblib")
    print("metrics:", metrics)

    # ---- persist forecasts + reorder recommendations to the DB ------------
    test_out = test_df[["material_id", "plant_id", "week_start"]].copy()
    test_out["forecast_qty"] = np.round(pred, 2)
    test_out["actual_qty"] = y_test.values
    test_out["model_name"] = MODEL_NAME
    test_out["week_start"] = pd.to_datetime(test_out["week_start"]).dt.date.astype(str)

    abc = abc_analysis(cons, materials)
    reorder = compute_reorder(cons, materials, snapshot, abc)
    inv_value = float((snapshot["on_hand_qty"] * snapshot["unit_cost_inr"]).sum())
    metrics["total_inventory_value_inr"] = round(inv_value, 2)
    metrics["skus_at_stockout_risk"] = int((reorder["stockout_risk"] != "LOW").sum())
    metrics["abc_counts"] = {k: int(v) for k, v in reorder["abc_class"].value_counts().items()}
    (RESULTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        try:
            test_out.to_sql("forecasts", conn, if_exists="replace", index=False)
            reorder.to_sql("reorder_recommendations", conn, if_exists="replace", index=False)
            conn.commit()
            print(f"wrote {len(test_out)} forecasts and {len(reorder)} reorder rows to DB")
        finally:
            conn.close()
    else:
        print("WARNING: inventory.db not found — run src/load_to_db.py first. "
              "Forecasts/reorder tables were not written to the DB.")

    # ---- charts -----------------------------------------------------------
    chart_df = test_out.rename(columns={"actual_qty": "actual_qty",
                                        "forecast_qty": "forecast_qty"})
    plot_forecast_vs_actual(chart_df, DOCS_DIR / "forecast_vs_actual.png")
    plot_abc_pareto(abc, DOCS_DIR / "abc_pareto.png")
    print(f"charts written to {DOCS_DIR}")
    print(f"model saved to {MODELS_DIR / 'demand_forecast.joblib'}")


if __name__ == "__main__":
    main()
