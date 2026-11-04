-- Checks that a dbt refactoring did not change any result: run once BEFORE the change to
-- snapshot the tables, rebuild with the new code, then run again AFTER to compare.
-- Used in phase 10a (portable SQL): 13 of 18 tables identical row by row; the other 5 differ
-- only in the last floating-point digits (max relative difference 1e-9), because aggregates
-- over doubles depend on row order and the trend slope changed from regr_slope to
-- covar_pop / var_pop.
--
--   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v mode=before' < scripts/compare_dbt_baseline.sql
--   ... change the models, dbt build ...
--   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v mode=after' < scripts/compare_dbt_baseline.sql
--
-- `before` copies every table of the marts and intermediate schemas (plus the two small
-- staging views) into the schema `dbt_baseline`. `after` reports, per table, the row counts and
-- the rows only on one side (`except all`, exact); for tables that differ, add a tolerance
-- comparison by grain with compare_table() at the end of this file. Drop `dbt_baseline` when done.
set statement_timeout = '900s';
\pset footer off
\if :{?mode}
\else
  \echo 'usage: psql -v mode=before|after'
  \quit
\endif

select :'mode' = 'before' as is_before \gset
\if :is_before
drop schema if exists dbt_baseline cascade;
create schema dbt_baseline;
do $$
declare r record;
begin
  for r in
    select table_schema, table_name from information_schema.tables
    where (table_schema in ('marts', 'intermediate') and table_type = 'BASE TABLE')
       or (table_schema = 'staging' and table_name in ('stg_bcb__ipca', 'stg_ibge__localities'))
    order by 1, 2
  loop
    execute format('create table dbt_baseline.%I as select * from %I.%I', r.table_name, r.table_schema, r.table_name);
  end loop;
end $$;
select count(*) as tables_copied from information_schema.tables where table_schema = 'dbt_baseline';
\quit
\endif

-- after: exact comparison
create temp table cmp (table_name text, schema_name text, rows_before bigint, rows_after bigint, only_before bigint, only_after bigint);
do $$
declare r record; s text; nb bigint; na bigint; ob bigint; oa bigint;
begin
  for r in select table_name from information_schema.tables where table_schema = 'dbt_baseline' order by 1 loop
    select table_schema into s from information_schema.tables
      where table_name = r.table_name and table_schema in ('marts', 'intermediate', 'staging') limit 1;
    execute format('select count(*) from dbt_baseline.%I', r.table_name) into nb;
    execute format('select count(*) from %I.%I', s, r.table_name) into na;
    execute format('select count(*) from (select * from dbt_baseline.%I except all select * from %I.%I) d', r.table_name, s, r.table_name) into ob;
    execute format('select count(*) from (select * from %I.%I except all select * from dbt_baseline.%I) d', s, r.table_name, r.table_name) into oa;
    insert into cmp values (r.table_name, s, nb, na, ob, oa);
  end loop;
end $$;
\echo '== exact comparison (only_before = only_after = 0 means identical)'
select * from cmp order by 1;

-- after: tolerance comparison by grain, for the tables that are not byte-identical
create temp table tol (table_name text, column_name text, data_type text, rows_joined bigint, null_mismatches bigint, value_mismatches bigint, max_rel_diff double precision);
create or replace function pg_temp.compare_table(t text, s text, keys text[]) returns void language plpgsql as $$
declare c record; joincond text; sql text; nj bigint; nm bigint; vm bigint; mrd double precision;
begin
  select string_agg(format('a.%I = b.%I', k, k), ' and ') into joincond from unnest(keys) k;
  for c in select column_name, data_type from information_schema.columns where table_schema = 'dbt_baseline' and table_name = t order by ordinal_position loop
    if c.column_name = any(keys) then continue; end if;
    if c.data_type in ('numeric', 'double precision', 'integer', 'bigint', 'real') then
      sql := format('select count(*), count(*) filter (where (a.%1$I is null) <> (b.%1$I is null)),
                     count(*) filter (where a.%1$I is not null and b.%1$I is not null and a.%1$I <> b.%1$I),
                     max(abs(a.%1$I::double precision - b.%1$I::double precision) / greatest(abs(a.%1$I::double precision), abs(b.%1$I::double precision), 1e-300))
                     from dbt_baseline.%2$I a join %3$I.%2$I b on %4$s', c.column_name, t, s, joincond);
    else
      sql := format('select count(*), count(*) filter (where (a.%1$I is null) <> (b.%1$I is null)),
                     count(*) filter (where a.%1$I is distinct from b.%1$I), null::double precision
                     from dbt_baseline.%2$I a join %3$I.%2$I b on %4$s', c.column_name, t, s, joincond);
    end if;
    execute sql into nj, nm, vm, mrd;
    insert into tol values (t, c.column_name, c.data_type, nj, nm, vm, mrd);
  end loop;
end $$;
select pg_temp.compare_table('int_climate__window_normals', 'intermediate', array['municipality_id', 'crop', 'window_name']);
select pg_temp.compare_table('fct_crop_climate', 'marts', array['municipality_id', 'crop', 'harvest_year']);
select pg_temp.compare_table('int_yield__territory_trend', 'intermediate', array['territory_level', 'territory_id', 'crop', 'harvest_year']);
select pg_temp.compare_table('agg_climate_yield_association', 'marts', array['territory_level', 'territory_id', 'crop', 'harvest_year']);
select pg_temp.compare_table('agg_climate_yield_association_summary', 'marts', array['territory_level', 'territory_id', 'crop']);
\echo '== tolerance comparison: rows joined must equal the row counts; mismatches must be 0'
select table_name, min(rows_joined) as rows_joined, sum(null_mismatches) as null_mismatches,
       sum(value_mismatches) filter (where max_rel_diff is null) as non_numeric_mismatches,
       count(*) filter (where value_mismatches > 0) as numeric_columns_differing, max(max_rel_diff) as max_rel_diff
from tol group by 1 order by 1;
\echo '== numeric columns with any difference, worst first'
select table_name, column_name, value_mismatches, max_rel_diff from tol where value_mismatches > 0 order by max_rel_diff desc limit 20;
