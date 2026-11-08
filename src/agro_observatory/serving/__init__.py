"""Serving layer: the small, pre-aggregated static files the website reads (phase 11).

The dbt models in dbt/models/serve are views over the marts; `export-serving` reads each view
once, from Postgres or BigQuery with the same code, writes the JSON files, the simplified
TopoJSON mesh and a manifest, validates every file against its JSON Schema (schemas/) and
reconciles the files with the marts. `package-serving` turns an exported version into the
data release. The contract is documented in docs/CONTRATO_DE_DADOS.md.
"""
