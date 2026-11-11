"""Streamlit dashboard — SAP Inventory & Demand Forecasting.

Run:  streamlit run app.py
Works from the repo root. If data/inventory.db or the trained model are
missing it falls back to the CSVs in data/ and tells you how to run the
full pipeline (python src/generate_data.py, python src/load_to_db.py,
python src/train.py).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "inventory.db"
METRICS_PATH = ROOT / "results" / "metrics.json"

st.set_page_config(page_title="SAP Inventory & Demand Forecasting", layout="wide")
st.title("📦 SAP Inventory & Demand Forecasting")
st.caption(
    "Synthetic SAP MM-style data · 40 materials × 3 plants (Delhi, Noida, Gurugram) · "
    "24 months of weekly consumption · RandomForest demand forecast"
)


@st.cache_data
def load_metrics() -> dict:
    if METRICS_PATH.exists():
        return json.loads(METRICS_PATH.read_text())
    return {}


@st.cache_data
def load_table(table: str) -> pd.DataFrame:
    """Prefer the SQLite DB; fall back to the matching CSV in data/."""
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                return pd.read_sql_query(f"SELECT * FROM {table}", conn)
        except Exception:
            pass
    csv_path = DATA_DIR / f"{table}.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


@st.cache_data
def load_forecasts() -> pd.DataFrame:
    df = load_table("forecasts")
    if not df.empty and "week_start" in df.columns:
        df["week_start"] = pd.to_datetime(df["week_start"])
    return df


@st.cache_data
def load_reorder() -> pd.DataFrame:
    return load_table("reorder_recommendations")


@st.cache_data
def load_consumption() -> pd.DataFrame:
    df = load_table("consumption_history")
    if not df.empty and "week_start" in df.columns:
        df["week_start"] = pd.to_datetime(df["week_start"])
    return df


def main() -> None:
    metrics = load_metrics()
    cons = load_consumption()
    forecasts = load_forecasts()
    reorder = load_reorder()
    snapshot = load_table("inventory_snapshot")
    materials = load_table("materials")

    if cons.empty:
        st.warning(
            "No data found. Run the pipeline first:\n\n"
            "```bash\npython src/generate_data.py\npython src/load_to_db.py\n"
            "python src/train.py\n```"
        )
        st.stop()

    # ---- sidebar filters ---------------------------------------------------
    st.sidebar.header("Filters")
    plant_options = sorted(cons["plant_id"].unique().tolist())
    plants = st.sidebar.multiselect("Plant", plant_options, default=plant_options)
    group_options = sorted(materials["material_group"].unique().tolist()) if not materials.empty else []
    groups = st.sidebar.multiselect("Material group", group_options, default=group_options)

    cons_f = cons[cons["plant_id"].isin(plants)]
    if not materials.empty and groups:
        mats = materials[materials["material_group"].isin(groups)]["material_id"]
        cons_f = cons_f[cons_f["material_id"].isin(mats)]
    reorder_f = reorder
    if not reorder.empty:
        reorder_f = reorder[reorder["plant_id"].isin(plants)]
        if not materials.empty and groups:
            reorder_f = reorder_f[reorder_f["material_id"].isin(mats)]

    # ---- KPI cards ---------------------------------------------------------
    mape = metrics.get("mape_pct")
    at_risk = int((reorder_f["stockout_risk"] != "LOW").sum()) if not reorder_f.empty else 0
    inv_value = (
        float((snapshot["on_hand_qty"] * snapshot["unit_cost_inr"]).sum())
        if not snapshot.empty else 0.0
    )
    # Service-level proxy: share of SKUs whose on-hand covers the reorder point.
    if not reorder_f.empty:
        covered = (reorder_f["on_hand_qty"] >= reorder_f["reorder_point"]).mean() * 100
    else:
        covered = 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Forecast MAPE (test)", f"{mape:.2f}%" if mape is not None else "—")
    c2.metric("SKUs at stockout risk", at_risk)
    c3.metric("Total inventory value", f"₹{inv_value:,.0f}")
    c4.metric("Service level proxy", f"{covered:.1f}%")

    # ---- charts ------------------------------------------------------------
    st.subheader("Forecast vs Actual (test set — last 12 weeks)")
    if not forecasts.empty:
        fc = forecasts[forecasts["plant_id"].isin(plants)]
        if not materials.empty and groups:
            fc = fc[fc["material_id"].isin(mats)]
        agg = fc.groupby("week_start")[["actual_qty", "forecast_qty"]].sum().reset_index()
        st.line_chart(agg.set_index("week_start"))
    else:
        st.info("No forecasts yet — run `python src/train.py` to generate them.")

    st.subheader("Stock by Plant")
    if not snapshot.empty:
        snap_f = snapshot[snapshot["plant_id"].isin(plants)]
        by_plant = snap_f.groupby("plant_id").apply(
            lambda d: (d["on_hand_qty"] * d["unit_cost_inr"]).sum(), include_groups=False
        )
        st.bar_chart(by_plant)

    st.subheader("ABC Pareto — annual consumption value by material")
    if not materials.empty and not cons.empty:
        cost = materials.set_index("material_id")["unit_cost_inr"]
        yearly = (
            cons_f.assign(value=cons_f["material_id"].map(cost) * cons_f["consumption_qty"])
            .groupby("material_id")["value"]
            .sum()
            .sort_values(ascending=False)
        )
        st.bar_chart(yearly.head(20))

    # ---- actionable recommendations -----------------------------------------
    st.subheader("Actionable Reorder Recommendations")
    if not reorder_f.empty:
        risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        rec = reorder_f.copy()
        rec["risk_rank"] = rec["stockout_risk"].map(risk_order)
        rec = rec.sort_values(["risk_rank", "recommended_order_qty"], ascending=[True, False])
        st.dataframe(
            rec[[
                "material_id", "plant_id", "abc_class", "on_hand_qty",
                "reorder_point", "safety_stock", "recommended_order_qty",
                "stockout_risk",
            ]],
            use_container_width=True,
        )
        high = rec[rec["stockout_risk"] == "HIGH"]
        if not high.empty:
            st.error(
                f"⚠️ {len(high)} SKU(s) at HIGH stockout risk — "
                "raise a purchase requisition now for the top rows above."
            )
    else:
        st.info("No reorder recommendations yet — run `python src/train.py` to generate them.")

    st.caption(
        "All data is synthetic. Safety stock = z × σ(demand) × √lead time; "
        "reorder point = avg weekly demand × lead time + safety stock."
    )


if __name__ == "__main__":
    main()
