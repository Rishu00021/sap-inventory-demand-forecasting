"""Smoke tests — run with:  python -m pytest tests/test_smoke.py -v"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA_DIR = ROOT / "data"


def test_data_files_exist():
    for name in ["materials.csv", "plants.csv", "consumption_history.csv",
                 "purchase_orders.csv", "inventory_snapshot.csv"]:
        assert (DATA_DIR / name).exists(), f"missing data/{name}"


def test_consumption_shape():
    df = pd.read_csv(DATA_DIR / "consumption_history.csv")
    # 40 materials x 3 plants x 104 weeks
    assert len(df) == 40 * 3 * 104
    assert df["consumption_qty"].min() >= 0
    assert set(df["plant_id"]) == {"P100", "P200", "P300"}
    assert df["material_id"].nunique() == 40


def test_metrics_json():
    metrics_path = ROOT / "results" / "metrics.json"
    assert metrics_path.exists(), "run src/train.py first"
    m = json.loads(metrics_path.read_text())
    for key in ["mae", "rmse", "mape_pct", "r2"]:
        assert key in m and m[key] >= 0
    assert m["r2"] > 0.5, f"R2 suspiciously low: {m['r2']}"
    assert m["mape_pct"] < 50, f"MAPE suspiciously high: {m['mape_pct']}"


def test_model_file_exists():
    assert (ROOT / "models" / "demand_forecast.joblib").exists()


def test_charts_exist():
    for name in ["forecast_vs_actual.png", "abc_pareto.png"]:
        p = ROOT / "docs" / name
        assert p.exists() and p.stat().st_size > 1000, f"missing chart {name}"


def test_db_tables_and_views():
    db = DATA_DIR / "inventory.db"
    assert db.exists(), "run src/load_to_db.py first"
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ["materials", "plants", "consumption_history", "purchase_orders",
                  "inventory_snapshot", "forecasts", "reorder_recommendations"]:
            assert t in tables, f"missing table {t}"
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")}
        assert {"v_stock_by_plant", "v_abc_analysis", "v_consumption_value"} <= views
        assert conn.execute("SELECT COUNT(*) FROM reorder_recommendations").fetchone()[0] == 120
        assert conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] > 0


def test_reorder_recommendations_sane():
    db = DATA_DIR / "inventory.db"
    with sqlite3.connect(db) as conn:
        df = pd.read_sql_query("SELECT * FROM reorder_recommendations", conn)
    assert (df["safety_stock"] >= 0).all()
    assert (df["reorder_point"] > 0).all()
    assert set(df["stockout_risk"]) <= {"HIGH", "MEDIUM", "LOW"}
    assert set(df["abc_class"]) <= {"A", "B", "C"}


def test_app_imports():
    import importlib.util

    spec = importlib.util.spec_from_file_location("app", ROOT / "app.py")
    assert spec is not None and spec.loader is not None
    # Importing app.py executes Streamlit page setup; it must not crash.
    # (Streamlit tolerates being imported outside `streamlit run`.)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
