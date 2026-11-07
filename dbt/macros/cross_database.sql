{#
  SQL that differs between dialects and has no cross-database macro in dbt-core. Each macro
  dispatches on the adapter: `default__` is Postgres (dev and CI), `bigquery__` is the
  production warehouse (phase 10). Everything else in the models uses dbt's own
  cross-database macros (type_int, type_string, bool_or, except, datediff, last_day,
  date_trunc; generate_series from dbt_utils) or SQL that both dialects share.
#}

{# A raw source column by its exact source name. Postgres keeps the API names verbatim
   (case-sensitive, some with hyphens), so they must be quoted. BigQuery column names are
   case-insensitive and cannot contain hyphens: the loader replaces "-" with "_" there, and
   this macro applies the same rename. #}
{% macro source_column(name) -%}
    {{ return(adapter.dispatch('source_column', 'agro_observatory')(name)) }}
{%- endmacro %}

{% macro default__source_column(name) -%}
    {{ adapter.quote(name) }}
{%- endmacro %}

{% macro bigquery__source_column(name) -%}
    {{ adapter.quote(name | replace('-', '_')) }}
{%- endmacro %}


{# True when `expression` matches the regular expression `pattern`. Write patterns in the
   subset POSIX (Postgres) and RE2 (BigQuery) share, e.g. [.] instead of \. #}
{% macro regex_match(expression, pattern) -%}
    {{ return(adapter.dispatch('regex_match', 'agro_observatory')(expression, pattern)) }}
{%- endmacro %}

{% macro default__regex_match(expression, pattern) -%}
    {{ expression }} ~ '{{ pattern }}'
{%- endmacro %}

{% macro bigquery__regex_match(expression, pattern) -%}
    regexp_contains({{ expression }}, r'{{ pattern }}')
{%- endmacro %}


{# Parses a string into a date. `format` uses strftime codes (%d, %m, %Y), BigQuery's native
   notation; Postgres gets the equivalent to_date pattern. #}
{% macro parse_date(expression, format) -%}
    {{ return(adapter.dispatch('parse_date', 'agro_observatory')(expression, format)) }}
{%- endmacro %}

{% macro default__parse_date(expression, format) -%}
    to_date({{ expression }}, '{{ format | replace('%d', 'DD') | replace('%m', 'MM') | replace('%Y', 'YYYY') }}')
{%- endmacro %}

{% macro bigquery__parse_date(expression, format) -%}
    parse_date('{{ format }}', {{ expression }})
{%- endmacro %}


{# A date from integer year, month and day expressions. dbt.date() only takes literals, so it
   cannot build a date from columns. #}
{% macro date_from_parts(year, month, day) -%}
    {{ return(adapter.dispatch('date_from_parts', 'agro_observatory')(year, month, day)) }}
{%- endmacro %}

{% macro default__date_from_parts(year, month, day) -%}
    make_date({{ year }}, {{ month }}, {{ day }})
{%- endmacro %}

{% macro bigquery__date_from_parts(year, month, day) -%}
    date({{ year }}, {{ month }}, {{ day }})
{%- endmacro %}


-- Ratios, logarithms and exponentials are computed in floating point on every warehouse. On
-- BigQuery a NUMERIC quotient (and LN or EXP of a NUMERIC) is rounded to 9 decimal places at
-- each step, which broke identities checked to 1e-9 (shares summing to 1, the growth
-- decomposition closing) and would make chained values (the IPCA index, log-linear trends)
-- drift from Postgres. NUMERIC stays for measured quantities (tonnes, hectares, money).
{% macro as_float(expression) -%}
    cast({{ expression }} as {{ dbt.type_float() }})
{%- endmacro %}
