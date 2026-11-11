-- ============================================================================
-- v_consumption_value — weekly consumption value + 4-week rolling average
-- per material-plant. Feeds the "what moved, and how fast" view of demand.
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_consumption_value AS
SELECT
    c.material_id,
    c.plant_id,
    c.week_start,
    c.week_number,
    c.consumption_qty,
    ROUND(c.consumption_qty * m.unit_cost_inr, 2) AS consumption_value_inr,
    ROUND(AVG(c.consumption_qty) OVER (
        PARTITION BY c.material_id, c.plant_id
        ORDER BY c.week_number
        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
    ), 1) AS rolling_4w_avg_qty
FROM consumption_history c
JOIN materials m ON m.material_id = c.material_id;
