-- 003: hromadné nahrávání vážení (viz docs/05_architektura.md)
--
-- Při COPY milionů řádků by se cizí klíče kontrolovaly u každého řádku zvlášť.
-- Proto se před nahráním dočasně odeberou a po nahrání znovu přidají:
-- PostgreSQL je pak ověří jedním dotazem nad celou tabulkou, což je řádově rychlejší.
-- Primární klíč zůstává po celou dobu (hlídá jedinečnost vážení).
-- Obě funkce se volají ve stejné transakci jako COPY, takže při chybě se vrátí vše.

CREATE FUNCTION weighing_bulk_load_begin() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    ALTER TABLE weighing DROP CONSTRAINT IF EXISTS weighing_scale_id_fkey;
    ALTER TABLE weighing DROP CONSTRAINT IF EXISTS weighing_run_id_fkey;
    ALTER TABLE weighing DROP CONSTRAINT IF EXISTS weighing_shift_id_fkey;
    DROP INDEX IF EXISTS ix_weighing_run;
    DROP INDEX IF EXISTS ix_weighing_time_brin;
END
$$;

CREATE FUNCTION weighing_bulk_load_end() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    CREATE INDEX IF NOT EXISTS ix_weighing_run       ON weighing (run_id, measured_at);
    CREATE INDEX IF NOT EXISTS ix_weighing_time_brin ON weighing USING brin (measured_at);
    ALTER TABLE weighing ADD CONSTRAINT weighing_scale_id_fkey FOREIGN KEY (scale_id) REFERENCES scale (scale_id);
    ALTER TABLE weighing ADD CONSTRAINT weighing_run_id_fkey   FOREIGN KEY (run_id)   REFERENCES production_run (run_id);
    ALTER TABLE weighing ADD CONSTRAINT weighing_shift_id_fkey FOREIGN KEY (shift_id) REFERENCES shift (shift_id);
END
$$;
