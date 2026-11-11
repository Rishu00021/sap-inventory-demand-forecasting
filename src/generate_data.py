"""Generate synthetic SAP-like inventory / consumption data.

All data is SYNTHETIC — no real employer data. It mimics the shape of
SAP MM tables (materials, plants, weekly consumption, purchase orders)
so the forecasting pipeline can be run end-to-end without any ERP access.

Output CSVs land in data/:
  materials.csv, plants.csv, consumption_history.csv,
  purchase_orders.csv, inventory_snapshot.csv
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

N_MATERIALS = 40
PLANTS = [
    ("P100", "Delhi Plant", "Delhi"),
    ("P200", "Noida Plant", "Noida"),
    ("P300", "Gurugram Plant", "Gurugram"),
]
N_WEEKS = 104  # 24 months of weekly consumption
START_WEEK = "2024-01-01"

# Material families with plausible base demand / cost / lead-time bands.
FAMILIES = [
    ("RM", "Raw Material", 60, 220, 40, 900, 2, 6),
    ("SP", "Spare Part", 5, 45, 150, 4200, 3, 8),
    ("PK", "Packaging", 120, 480, 8, 120, 1, 3),
    ("CN", "Consumable", 25, 140, 20, 350, 1, 4),
]


def _seasonal(week_of_year: int, phase: float) -> float:
    """Annual seasonality: peak around Diwali/festive quarter (weeks ~40-48)."""
    return 1.0 + 0.35 * math.sin(2 * math.pi * (week_of_year - 10 + phase) / 52.0)


def main(seed: int = 42) -> None:
    rng = random.Random(seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- plants ---------------------------------------------------------
    with open(DATA_DIR / "plants.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["plant_id", "plant_name", "city"])
        w.writerows(PLANTS)

    # ---- materials ------------------------------------------------------
    materials = []
    for i in range(1, N_MATERIALS + 1):
        prefix, family, lo, hi, cost_lo, cost_hi, lt_lo, lt_hi = rng.choice(FAMILIES)
        mat_id = f"MAT-{prefix}-{i:03d}"
        base = rng.uniform(lo, hi)
        materials.append(
            {
                "material_id": mat_id,
                "description": f"{family} {i:02d} ({prefix})",
                "material_group": family,
                "base_unit": "EA",
                "unit_cost_inr": round(rng.uniform(cost_lo, cost_hi), 2),
                "lead_time_weeks": rng.randint(lt_lo, lt_hi),
                "base_weekly_demand": round(base, 2),
                "trend_pct": round(rng.uniform(-0.15, 0.45), 3),  # annual trend
                "season_phase": rng.uniform(0, 8),
                "safety_factor": rng.choice([1.28, 1.65, 1.96]),
            }
        )
    with open(DATA_DIR / "materials.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(materials[0].keys()))
        w.writeheader()
        w.writerows(materials)

    # ---- weekly consumption history --------------------------------------
    import datetime as dt

    start = dt.date.fromisoformat(START_WEEK)
    cons_rows = []
    for m in materials:
        for plant_id, _, _ in PLANTS:
            # Plant-level demand multiplier (Delhi biggest, Gurugram smallest)
            plant_mult = {"P100": 1.0, "P200": 0.75, "P300": 0.55}[plant_id]
            for wk in range(N_WEEKS):
                week_start = start + dt.timedelta(weeks=wk)
                week_of_year = week_start.isocalendar()[1]
                trend = 1.0 + m["trend_pct"] * (wk / N_WEEKS)
                seasonal = _seasonal(week_of_year, m["season_phase"])
                noise = rng.gauss(1.0, 0.18)
                qty = m["base_weekly_demand"] * plant_mult * trend * seasonal * noise
                qty = max(0, round(qty))
                cons_rows.append(
                    {
                        "material_id": m["material_id"],
                        "plant_id": plant_id,
                        "week_start": week_start.isoformat(),
                        "week_number": wk + 1,
                        "consumption_qty": qty,
                    }
                )
    with open(DATA_DIR / "consumption_history.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cons_rows[0].keys()))
        w.writeheader()
        w.writerows(cons_rows)

    # ---- purchase orders (synthetic, sparse) ------------------------------
    po_rows = []
    po_no = 4500000000
    for m in materials:
        for plant_id, _, _ in PLANTS:
            for _ in range(rng.randint(6, 14)):
                wk = rng.randint(0, N_WEEKS - 4)
                order_date = start + dt.timedelta(weeks=wk)
                qty = round(m["base_weekly_demand"] * rng.uniform(2, 6))
                po_rows.append(
                    {
                        "po_number": po_no,
                        "material_id": m["material_id"],
                        "plant_id": plant_id,
                        "order_date": order_date.isoformat(),
                        "quantity": qty,
                        "unit_cost_inr": m["unit_cost_inr"],
                        "status": rng.choice(["Received", "Received", "Received", "Open"]),
                    }
                )
                po_no += 1
    with open(DATA_DIR / "purchase_orders.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(po_rows[0].keys()))
        w.writeheader()
        w.writerows(po_rows)

    # ---- inventory snapshot (latest week) ---------------------------------
    snap_rows = []
    last_week_qty = {}
    for r in cons_rows:
        if r["week_number"] == N_WEEKS:
            last_week_qty[(r["material_id"], r["plant_id"])] = r["consumption_qty"]
    for m in materials:
        for plant_id, _, _ in PLANTS:
            weekly = last_week_qty[(m["material_id"], plant_id)]
            # Opening stock: roughly 0.5-12 weeks of cover, some SKUs deliberately low
            cover = rng.uniform(0.5, 12.0)
            on_hand = max(0, round(weekly * cover))
            snap_rows.append(
                {
                    "material_id": m["material_id"],
                    "plant_id": plant_id,
                    "on_hand_qty": on_hand,
                    "snapshot_date": (start + dt.timedelta(weeks=N_WEEKS - 1)).isoformat(),
                    "unit_cost_inr": m["unit_cost_inr"],
                }
            )
    with open(DATA_DIR / "inventory_snapshot.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(snap_rows[0].keys()))
        w.writeheader()
        w.writerows(snap_rows)

    print(f"materials:            {len(materials)}")
    print(f"plants:               {len(PLANTS)}")
    print(f"consumption rows:     {len(cons_rows)}")
    print(f"purchase order rows:  {len(po_rows)}")
    print(f"inventory rows:       {len(snap_rows)}")
    print(f"CSVs written to {DATA_DIR}")


if __name__ == "__main__":
    main()
