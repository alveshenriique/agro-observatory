{#
  Macros of the serving layer (models/serve), which feeds the static files of the website.
#}

{# The published series of a crop and year. Coffee total is split at the unit break of the
   PAM (coffee "em coco" until 2001, "beneficiado" from 2002): the two halves are different
   series, so no series, ranking, share or concentration published by the serving layer
   crosses the break. The husk-to-processed ratio varies between regions, so even unit-free
   measures (shares, HHI) could move artificially at the break. #}
{% macro serve_series(crop, year) -%}
    case
        when {{ crop }} = 'coffee_total' and {{ year }} < {{ var('coffee_unit_break_year') }}
            then 'coffee_in_husk'
        when {{ crop }} = 'coffee_total' then 'coffee_processed'
        else {{ crop }}
    end
{%- endmacro %}


{# Rounds to a fixed number of decimal places, identically on Postgres and BigQuery: the value
   goes through NUMERIC (decimal) before rounding, so a double like 0.145 rounds as the decimal
   0.145 on both. Postgres has no round(double precision, integer), and BigQuery's ROUND of a
   FLOAT64 rounds the binary value. The result is NUMERIC on both warehouses. #}
{% macro round_to(expression, digits) -%}
    round(cast({{ expression }} as numeric), {{ digits }})
{%- endmacro %}


{# A rounded measured quantity as an integer (tonnes, hectares, thousand reais). #}
{% macro round_to_int(expression) -%}
    cast(round(cast({{ expression }} as numeric), 0) as {{ dbt.type_bigint() }})
{%- endmacro %}
