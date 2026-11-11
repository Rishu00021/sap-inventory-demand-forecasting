-- ============================================================================
-- v_abc_analysis — ABC classification by annual consumption value
-- A = top 80% of value, B = next 15%, C = remaining 5%.
-- Uses a window function (MySQL 8.0+ / SQLite 3.25+).
-- ============================================================================
CREATE VIEW IF NOT EXISTS v_abc_analysis AS
WITH yearly AS (
    SELECT
        c.material_id,
        m.description,
        m.material_group,
        SUM(c.consumption_qty) AS annual_qty,
        SUM(c.consumption_qty * m.unit_cost_inr) AS annual_value_inr
    FROM consumption_history c
    JOIN materials m ON m.material_id = c.material_id
    GROUP BY c.material_id, m.description, m.material_group
),
ranked AS (
    SELECT
        *,
        SUM(annual_value_inr) OVER () AS total_value,
        SUM(annual_value_inr) OVER (
            ORDER BY annual_value_inr DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cum_value
    FROM yearly
)
SELECT
    material_id,
    description,
    material_group,
    annual_qty,
    ROUND(annual_value_inr, 2) AS annual_value_inr,
    ROUND(100.0 * annual_value_inr / total_value, 2) AS pct_of_value,
    CASE
        WHEN cum_value / total_value <= 0.80 THEN 'A'
        WHEN cum_value / total_value <= 0.95 THEN 'B'
        ELSE 'C'
    END AS abc_class
FROM ranked
ORDER BY annual_value_inr DESC;
