-- The daily climate (~94 million rows) is processed only on the local Postgres. A warehouse
-- without it (the BigQuery production target) reads the window indicators already computed on
-- Postgres from the derived source `raw.climate_window_indicators` instead of recomputing them,
-- and the models and tests that read the daily climate are disabled there. Everything
-- downstream refs `int_climate__window_indicators` as usual, so the rest of the project is the
-- same on both targets. The var lets the derived path be tested on Postgres too
-- (`--vars '{use_derived_climate_source: true}'`), as CI does.
{% macro use_derived_climate_source() %}
    {{ return(var('use_derived_climate_source', target.type == 'bigquery')) }}
{% endmacro %}


-- Every write to BigQuery consumes the sandbox's lifetime storage quota, so writing commands
-- (run, build, seed, snapshot) on a BigQuery target stop here unless they come through
-- `uv run bq-dbt`, which shows the quota estimate, asks for confirmation and sets the variable
-- below. dbt creates the (empty) datasets before this hook runs; that uses no storage.
{% macro guard_bigquery_writes() %}
    {% if execute and target.type == 'bigquery'
        and invocation_args_dict.get('which') in ('run', 'build', 'seed', 'snapshot')
        and env_var('AGRO_CONFIRM_BIGQUERY_WRITE', '') != 'yes' %}
        {{ exceptions.raise_compiler_error(
            "Writing to BigQuery consumes the sandbox's lifetime storage quota. Run it through "
            "`uv run bq-dbt " ~ invocation_args_dict.get('which') ~ " ...`, which shows the quota "
            "estimate and asks for confirmation."
        ) }}
    {% endif %}
{% endmacro %}
