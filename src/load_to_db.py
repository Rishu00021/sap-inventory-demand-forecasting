"""Load generated CSVs into a SQLite database (runnable demo).

The DDL in schema.sql is written for MySQL; this loader applies the
equivalent SQLite-compatible DDL and additionally creates the analytical
views defined in sql/. SQLite is used here only so the project runs
anywhere with zero setup — the schema and queries are MySQL-flavoured.

Creates data/inventory.db (gitignored) with tables:
  materials, plants, consumption_history, purchase_orders,
  inventory_snapshot, forecasts, reorder_recommendations
plus views: v_stock_by_plant, v_abc_analysis, v_consumption_value
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "inventory.db"
SQL_DIR = ROOT / "sql"

TABLES = [
    "materials",
    "plants",
    "consumption_history",
    "purchase_orders",
    "inventory_snapshot",
]

DDL = """
CREATE TABLE IF NOT EXISTS materials (
    material_id TEXT PRIMARY KEY,
    description TEXT,
    material_group TEXT,
    base_unit TEXT,
    unit_cost_inr REAL,
    lead_time_weeks INTEGER,
    base_weekly_demand REAL,
    trend_pct REAL,
    season_phase REAL,
    safety_factor REAL
);
CREATE TABLE IF NOT EXISTS plants (
    plant_id TEXT PRIMARY KEY,
    plant_name TEXT,
    city TEXT
);
CREATE TABLE IF NOT EXISTS consumption_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_number INTEGER NOT NULL,
    consumption_qty INTEGER NOT NULL,
    FOREIGN KEY (material_id) REFERENCES materials(material_id),
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number INTEGER PRIMARY KEY,
    material_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    order_date TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_cost_inr REAL,
    status TEXT,
    FOREIGN KEY (material_id) REFERENCES materials(material_id),
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);
CREATE TABLE IF NOT EXISTS inventory_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    on_hand_qty INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    unit_cost_inr REAL,
    FOREIGN KEY (material_id) REFERENCES materials(material_id),
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    forecast_qty REAL NOT NULL,
    actual_qty REAL,
    model_name TEXT
);
CREATE TABLE IF NOT EXISTS reorder_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    plant_id TEXT NOT NULL,
    avg_weekly_demand REAL,
    demand_std REAL,
    safety_stock REAL,
    reorder_point REAL,
    on_hand_qty INTEGER,
    recommended_order_qty REAL,
    stockout_risk TEXT,
    abc_class TEXT,
    generated_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_cons_mat_plant
    ON consumption_history(material_id, plant_id, week_number);
CREATE INDEX IF NOT EXISTS idx_cons_week ON consumption_history(week_number);
"""


def load_csvs(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        csv_path = DATA_DIR / f"{table}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing {csv_path} — run src/generate_data.py first.")
        df = pd.read_csv(csv_path)
        df.to_sql(table, conn, if_exists="replace", index=False)
        print(f"loaded {table}: {len(df)} rows")


def create_views(conn: sqlite3.Connection) -> None:
    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        sql = sql_file.read_text()
        conn.executescript(sql)
        print(f"applied view(s) from sql/{sql_file.name}")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(DDL)
        load_csvs(conn)
        create_views(conn)
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM consumption_history")
        print(f"consumption_history rows in DB: {cur.fetchone()[0]}")
        print(f"Database ready at {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
