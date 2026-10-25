-- 001: tabulky, výčtové typy a integritní omezení
-- Návrh: docs/03_logicke_schema.md

CREATE EXTENSION IF NOT EXISTS btree_gist;  -- EXCLUDE s rovností (line_id WITH =)

CREATE TYPE weighing_result AS ENUM ('OK', 'UNDER', 'OVER');
CREATE TYPE alert_type      AS ENUM ('SCALE_DRIFT', 'CREW_QUALITY', 'CHANGEOVER_RAMPUP');
CREATE TYPE alert_severity  AS ENUM ('INFO', 'WARNING', 'CRITICAL');

-- ---------------------------------------------------------------- kmenová data

CREATE TABLE line (
    line_id            smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code               varchar(10) NOT NULL UNIQUE,
    name               text        NOT NULL,
    nominal_speed_ppm  smallint    NOT NULL CHECK (nominal_speed_ppm > 0)
);
COMMENT ON TABLE line IS 'Balicí linka (PP-01 až PP-08)';

CREATE TABLE scale (
    scale_id       smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           varchar(10)  NOT NULL UNIQUE,
    serial_number  varchar(40)  NOT NULL UNIQUE,
    resolution_g   numeric(4,3) NOT NULL CHECK (resolution_g > 0),
    line_id        smallint     NOT NULL UNIQUE REFERENCES line (line_id)
);
COMMENT ON TABLE scale IS 'Kontrolní váha, na každé lince právě jedna';

CREATE TABLE calibration (
    scale_id         smallint     NOT NULL REFERENCES scale (scale_id),
    calibrated_at    timestamptz  NOT NULL,
    offset_before_g  numeric(6,3) NOT NULL,
    performed_by     text         NOT NULL,
    PRIMARY KEY (scale_id, calibrated_at)
);
COMMENT ON TABLE calibration IS 'Kalibrace váhy (slabá entita, klíč = váha + čas)';

CREATE TABLE element (
    element_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    element_no  varchar(20)  NOT NULL UNIQUE,
    name        text         NOT NULL,
    weight_g    numeric(6,3) NOT NULL CHECK (weight_g > 0)
);

CREATE TABLE product (
    product_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_no     varchar(20)  NOT NULL UNIQUE,
    name           text         NOT NULL,
    film_weight_g  numeric(5,3) NOT NULL CHECK (film_weight_g > 0)
);
COMMENT ON TABLE product IS 'Výrobek = druh sáčku. Cílová hmotnost a tolerance jsou v pohledu v_product_spec.';

CREATE TABLE product_element (
    product_id  integer  NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    element_id  integer  NOT NULL REFERENCES element (element_id),
    quantity    smallint NOT NULL CHECK (quantity >= 1),
    PRIMARY KEY (product_id, element_id)
);
CREATE INDEX ix_product_element_element ON product_element (element_id);
COMMENT ON TABLE product_element IS 'Složení sáčku (rozklad vztahu M:N výrobek-dílek)';

CREATE TABLE crew (
    crew_id               smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                  char(1)  NOT NULL UNIQUE CHECK (code ~ '^[A-Z]$'),
    rotation_offset_days  smallint NOT NULL CHECK (rotation_offset_days BETWEEN 0 AND 7),
    description           text
);
COMMENT ON TABLE crew IS 'Parta A-D, rotace 2-2-4';

CREATE TABLE shift_type (
    shift_type_id   smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            char(1)  NOT NULL UNIQUE,
    name            text     NOT NULL,
    start_time      time     NOT NULL,
    duration_hours  smallint NOT NULL CHECK (duration_hours BETWEEN 1 AND 24)
);

-- ---------------------------------------------------------------- provozní data

CREATE TABLE shift (
    shift_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_date     date        NOT NULL,
    shift_type_id  smallint    NOT NULL REFERENCES shift_type (shift_type_id),
    crew_id        smallint    NOT NULL REFERENCES crew (crew_id),
    starts_at      timestamptz NOT NULL,
    ends_at        timestamptz NOT NULL,
    UNIQUE (shift_date, shift_type_id),
    CHECK (ends_at > starts_at),
    -- IO6: směny se nepřekrývají
    CONSTRAINT ex_shift_no_overlap EXCLUDE USING gist (tstzrange(starts_at, ends_at) WITH &&)
);
CREATE INDEX ix_shift_crew ON shift (crew_id);

CREATE TABLE production_run (
    run_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_no       varchar(20) NOT NULL UNIQUE,
    line_id      smallint    NOT NULL REFERENCES line (line_id),
    product_id   integer     NOT NULL REFERENCES product (product_id),
    starts_at    timestamptz NOT NULL,
    ends_at      timestamptz NOT NULL,
    planned_qty  integer     NOT NULL CHECK (planned_qty > 0),
    CHECK (ends_at > starts_at),
    -- IO5: zakázky na jedné lince se nepřekrývají
    CONSTRAINT ex_run_no_overlap EXCLUDE USING gist (line_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
);
CREATE INDEX ix_run_product ON production_run (product_id);
COMMENT ON TABLE production_run IS 'Zakázka = výroba jednoho výrobku na jedné lince';

CREATE TABLE weighing (
    scale_id     smallint        NOT NULL REFERENCES scale (scale_id),
    measured_at  timestamptz     NOT NULL,
    run_id       integer         NOT NULL REFERENCES production_run (run_id),
    shift_id     integer         NOT NULL REFERENCES shift (shift_id),
    weight_g     numeric(6,2)    NOT NULL CHECK (weight_g > 0),
    result       weighing_result NOT NULL,
    PRIMARY KEY (scale_id, measured_at)
) PARTITION BY RANGE (measured_at);
COMMENT ON TABLE weighing IS 'Jedno vážení jednoho sáčku. Rozděleno po dnech.';
COMMENT ON COLUMN weighing.shift_id IS 'Řízená denormalizace: směna jde dopočítat z času, ukládá se kvůli rychlosti.';

CREATE INDEX ix_weighing_run       ON weighing (run_id, measured_at);
CREATE INDEX ix_weighing_time_brin ON weighing USING brin (measured_at);
CREATE TABLE weighing_default PARTITION OF weighing DEFAULT;

-- Založí denní oddíly tabulky weighing pro dny <p_from, p_to).
CREATE FUNCTION create_weighing_partitions(p_from date, p_to date) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    d       date    := p_from;
    created integer := 0;
    part    text;
BEGIN
    WHILE d < p_to LOOP
        part := format('weighing_%s', to_char(d, 'YYYYMMDD'));
        IF to_regclass(part) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF weighing FOR VALUES FROM (%L) TO (%L)',
                part, d::timestamptz, (d + 1)::timestamptz);
            created := created + 1;
        END IF;
        d := d + 1;
    END LOOP;
    RETURN created;
END
$$;

CREATE TABLE alert (
    alert_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz    NOT NULL DEFAULT now(),
    alert_type  alert_type     NOT NULL,
    severity    alert_severity NOT NULL,
    line_id     smallint       NOT NULL REFERENCES line (line_id),
    scale_id    smallint       REFERENCES scale (scale_id),
    crew_id     smallint       REFERENCES crew (crew_id),
    valid_from  timestamptz    NOT NULL,
    valid_to    timestamptz,
    message     text           NOT NULL,
    details     jsonb          NOT NULL DEFAULT '{}'::jsonb,
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK (alert_type <> 'SCALE_DRIFT'  OR scale_id IS NOT NULL),
    CHECK (alert_type <> 'CREW_QUALITY' OR crew_id  IS NOT NULL)
);
CREATE INDEX ix_alert_line ON alert (line_id, valid_from);
COMMENT ON TABLE alert IS 'Upozornění vytvořená analýzou';
