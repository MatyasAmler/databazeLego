-- 002: analytická vrstva - odvozené atributy, hodinové souhrny a pohledy pro detektory
-- viz docs/03_logicke_schema.md

-- IO1, IO2: cílová hmotnost a tolerance výrobku ze složení
CREATE VIEW v_product_spec AS
SELECT p.product_id,
       p.product_no,
       p.name,
       round(sum(pe.quantity * e.weight_g) + p.film_weight_g, 2) AS target_weight_g,
       round(min(e.weight_g) / 2, 2)                               AS tolerance_g
FROM product p
JOIN product_element pe ON pe.product_id = p.product_id
JOIN element e          ON e.element_id  = pe.element_id
GROUP BY p.product_id, p.product_no, p.name, p.film_weight_g;

-- Hodinový souhrn pro každou kombinaci váha x zakázka x směna.
-- "Rozběh" = prvních 20 minut zakázky (stejná hodnota jako Settings.rampup_minutes).
CREATE MATERIALIZED VIEW mv_hourly_stats AS
SELECT w.scale_id,
       r.line_id,
       w.run_id,
       w.shift_id,
       date_trunc('hour', w.measured_at)                                   AS hour,
       count(*)                                                            AS n,
       count(*) FILTER (WHERE w.result = 'OK')                             AS n_ok,
       count(*) FILTER (WHERE w.result = 'UNDER')                          AS n_under,
       count(*) FILTER (WHERE w.result = 'OVER')                           AS n_over,
       count(*) FILTER (WHERE w.measured_at <  r.starts_at + interval '20 minutes')                          AS n_rampup,
       count(*) FILTER (WHERE w.measured_at <  r.starts_at + interval '20 minutes' AND w.result = 'UNDER')  AS n_rampup_under,
       count(*) FILTER (WHERE w.measured_at <  r.starts_at + interval '20 minutes' AND w.result = 'OVER')   AS n_rampup_over,
       count(*) FILTER (WHERE w.measured_at >= r.starts_at + interval '20 minutes' AND w.result = 'OK')     AS n_ok_steady,
       sum(w.weight_g - ps.target_weight_g)
           FILTER (WHERE w.measured_at >= r.starts_at + interval '20 minutes' AND w.result = 'OK')          AS sum_dev_ok_steady
FROM weighing w
JOIN production_run r  ON r.run_id = w.run_id
JOIN v_product_spec ps ON ps.product_id = r.product_id
GROUP BY w.scale_id, r.line_id, w.run_id, w.shift_id, date_trunc('hour', w.measured_at)
WITH NO DATA;

CREATE UNIQUE INDEX ux_mv_hourly_stats ON mv_hourly_stats (scale_id, run_id, shift_id, hour);
CREATE INDEX ix_mv_hourly_stats_hour   ON mv_hourly_stats (hour);

-- Regulační diagram: hodinový průměr odchylky dobrých sáčků (bez rozběhů) a výmět pro každou váhu
CREATE VIEW v_scale_hourly AS
SELECT h.scale_id,
       s.code                                                     AS scale_code,
       h.line_id,
       l.code                                                     AS line_code,
       h.hour,
       sum(h.n)                                                   AS n,
       sum(h.n_ok_steady)                                         AS n_ok_steady,
       sum(h.n_under + h.n_over)                                  AS n_rejected,
       sum(h.n_over)                                              AS n_over,
       sum(h.n_under + h.n_over)::numeric / sum(h.n)              AS reject_rate,
       sum(h.sum_dev_ok_steady) / nullif(sum(h.n_ok_steady), 0)   AS mean_dev_ok
FROM mv_hourly_stats h
JOIN scale s ON s.scale_id = h.scale_id
JOIN line l  ON l.line_id  = h.line_id
GROUP BY h.scale_id, s.code, h.line_id, l.code, h.hour;

-- Podváha (chybějící dílek) v ustáleném provozu podle linky x typu směny x party
CREATE VIEW v_quality_by_crew AS
SELECT l.code                                                    AS line_code,
       h.line_id,
       st.code                                                   AS shift_type_code,
       c.code                                                    AS crew_code,
       c.crew_id,
       count(DISTINCT h.shift_id)                                AS shifts,
       sum(h.n - h.n_rampup)                                     AS n_steady,
       sum(h.n_under - h.n_rampup_under)                         AS n_under_steady,
       sum(h.n_under - h.n_rampup_under)::numeric
           / nullif(sum(h.n - h.n_rampup), 0)                    AS under_rate
FROM mv_hourly_stats h
JOIN shift sh      ON sh.shift_id = h.shift_id
JOIN shift_type st ON st.shift_type_id = sh.shift_type_id
JOIN crew c        ON c.crew_id = sh.crew_id
JOIN line l        ON l.line_id = h.line_id
GROUP BY l.code, h.line_id, st.code, c.code, c.crew_id;

-- Výmět v rozběhu (prvních 20 minut zakázky) a v ustáleném provozu podle linky
CREATE VIEW v_rampup_by_line AS
SELECT l.code                                                              AS line_code,
       h.line_id,
       count(DISTINCT h.run_id)                                            AS runs,
       sum(h.n_rampup)                                                     AS n_rampup,
       sum(h.n_rampup_under + h.n_rampup_over)                             AS n_rampup_rejected,
       sum(h.n_rampup_under + h.n_rampup_over)::numeric
           / nullif(sum(h.n_rampup), 0)                                    AS rampup_reject_rate,
       sum(h.n_under + h.n_over - h.n_rampup_under - h.n_rampup_over)::numeric
           / nullif(sum(h.n - h.n_rampup), 0)                              AS steady_reject_rate
FROM mv_hourly_stats h
JOIN line l ON l.line_id = h.line_id
GROUP BY l.code, h.line_id;
