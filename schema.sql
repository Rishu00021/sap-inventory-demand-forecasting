-- ============================================================================
-- SAP Inventory & Demand Forecasting — MySQL schema
-- ============================================================================
-- Written for MySQL 8.0. The runnable demo in this repo uses SQLite
-- (see src/load_to_db.py) with the equivalent DDL, so the project works
-- with zero setup; this file shows the production-flavoured MySQL DDL
-- and the SQL skill used to design it.
-- All data is SYNTHETIC — no real employer data.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS sap_inventory
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
USE sap_inventory;

-- ---------------------------------------------------------------------------
-- Master data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plants (
    plant_id   VARCHAR(10)  NOT NULL,
    plant_name VARCHAR(100) NOT NULL,
    city       VARCHAR(50)  NOT NULL,
    PRIMARY KEY (plant_id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS materials (
    material_id        VARCHAR(20)   NOT NULL,
    description        VARCHAR(200)  NOT NULL,
    material_group     VARCHAR(20)   NOT NULL,
    base_unit          VARCHAR(10)   NOT NULL DEFAULT 'EA',
    unit_cost_inr      DECIMAL(12,2) NOT NULL,
    lead_time_weeks    INT           NOT NULL,
    base_weekly_demand DECIMAL(10,2) NOT NULL,
    trend_pct          DECIMAL(6,3)  NOT NULL DEFAULT 0,
    season_phase       DECIMAL(6,3)  NOT NULL DEFAULT 0,
    safety_factor      DECIMAL(4,2)  NOT NULL DEFAULT 1.65,
    PRIMARY KEY (material_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------------
-- Transactional data (SAP MM style)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consumption_history (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    material_id     VARCHAR(20)  NOT NULL,
    plant_id        VARCHAR(10)  NOT NULL,
    week_start      DATE         NOT NULL,
    week_number     INT          NOT NULL,
    consumption_qty INT          NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_cons_mat_plant (material_id, plant_id, week_number),
    INDEX idx_cons_week (week_number),
    CONSTRAINT fk_cons_material FOREIGN KEY (material_id)
        REFERENCES materials (material_id),
    CONSTRAINT fk_cons_plant FOREIGN KEY (plant_id)
        REFERENCES plants (plant_id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number     BIGINT        NOT NULL,
    material_id   VARCHAR(20)   NOT NULL,
    plant_id      VARCHAR(10)   NOT NULL,
    order_date    DATE          NOT NULL,
    quantity      INT           NOT NULL,
    unit_cost_inr DECIMAL(12,2) NOT NULL,
    status        VARCHAR(20)   NOT NULL DEFAULT 'Open',
    PRIMARY KEY (po_number),
    INDEX idx_po_material (material_id, plant_id),
    CONSTRAINT fk_po_material FOREIGN KEY (material_id)
        REFERENCES materials (material_id),
    CONSTRAINT fk_po_plant FOREIGN KEY (plant_id)
        REFERENCES plants (plant_id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS inventory_snapshot (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    material_id   VARCHAR(20)   NOT NULL,
    plant_id      VARCHAR(10)   NOT NULL,
    on_hand_qty   INT           NOT NULL,
    snapshot_date DATE          NOT NULL,
    unit_cost_inr DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_inv_mat_plant (material_id, plant_id),
    CONSTRAINT fk_inv_material FOREIGN KEY (material_id)
        REFERENCES materials (material_id),
    CONSTRAINT fk_inv_plant FOREIGN KEY (plant_id)
        REFERENCES plants (plant_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------------
-- Model outputs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    id           BIGINT        NOT NULL AUTO_INCREMENT,
    material_id  VARCHAR(20)   NOT NULL,
    plant_id     VARCHAR(10)   NOT NULL,
    week_start   DATE          NOT NULL,
    forecast_qty DECIMAL(10,2) NOT NULL,
    actual_qty   INT           NULL,
    model_name   VARCHAR(50)   NULL,
    PRIMARY KEY (id),
    INDEX idx_fc_mat_plant (material_id, plant_id, week_start)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS reorder_recommendations (
    id                     BIGINT        NOT NULL AUTO_INCREMENT,
    material_id            VARCHAR(20)   NOT NULL,
    plant_id               VARCHAR(10)   NOT NULL,
    avg_weekly_demand      DECIMAL(10,2) NOT NULL,
    demand_std             DECIMAL(10,2) NOT NULL,
    safety_stock           DECIMAL(10,2) NOT NULL,
    reorder_point          DECIMAL(10,2) NOT NULL,
    on_hand_qty            INT           NOT NULL,
    recommended_order_qty  DECIMAL(10,2) NOT NULL,
    stockout_risk          VARCHAR(10)   NOT NULL,
    abc_class              CHAR(1)       NOT NULL,
    generated_date         DATE          NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_rr_risk (stockout_risk),
    INDEX idx_rr_abc (abc_class)
) ENGINE = InnoDB;
