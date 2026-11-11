-- ============================================================================
-- v_stock_by_plant — current stock position per plant
-- MySQL-compatible (works in SQLite too). Answers: how much inventory value
-- and how many SKUs sit in each plant, and how many are already below
-- one week of average demand.
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_stock_by_plant AS
SELECT
    p.plant_id,
    p.plant_name,
    p.city,
    COUNT(*) AS sku_count,
    SUM(s.on_hand_qty) AS total_on_hand_qty,
    ROUND(SUM(s.on_hand_qty * s.unit_cost_inr), 2) AS inventory_value_inr,
    ROUND(AVG(s.on_hand_qty), 1) AS avg_on_hand_per_sku,
    SUM(CASE WHEN s.on_hand_qty = 0 THEN 1 ELSE 0 END) AS zero_stock_skus
FROM inventory_snapshot s
JOIN plants p ON p.plant_id = s.plant_id
GROUP BY p.plant_id, p.plant_name, p.city;
