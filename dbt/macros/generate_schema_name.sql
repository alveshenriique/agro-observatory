-- Use the custom schema name as-is (e.g. "staging"), instead of dbt's default
-- "<target schema>_<custom schema>" (e.g. "dbt_staging").
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
