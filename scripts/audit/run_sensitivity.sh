#!/usr/bin/env bash
# Sensitivity analysis: rebuild the climate chain with alternative thresholds and window rules
# (dbt vars / regenerated calendar seed), collect the metrics after each variation, and restore
# the defaults at the end. The models themselves are not changed. Uses its own dbt target and
# log paths so it can run alongside other dbt commands.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=${1:-/tmp/atlas_sensitivity}
mkdir -p "$OUT"
DBT="uv run --env-file ../.env dbt"
PATHS="--target-path target_audit --log-path logs_audit"

metrics() {  # name
  docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q' \
    < scripts/audit/sensitivity_metrics.sql > "$OUT/metrics_$1.txt" 2>&1
  echo "metrics: $1"
}
run_chain() {  # name select vars
  (cd dbt && $DBT run --select "$2" --vars "$3" $PATHS > "$OUT/run_$1.log" 2>&1) && echo "run ok: $1" || { echo "RUN FAILED: $1"; tail -5 "$OUT/run_$1.log"; }
}
reseed_windows() {  # shift
  uv run python scripts/make_calendar_windows.py --critical-shift "$1" > /dev/null
  (cd dbt && $DBT seed --select crop_calendar_windows $PATHS > "$OUT/seed_shift$1.log" 2>&1)
}

metrics baseline
run_chain z05 "agg_climate_yield_association+" '{stress_z_threshold: 0.5}'; metrics z05
run_chain z15 "agg_climate_yield_association+" '{stress_z_threshold: 1.5}'; metrics z15
run_chain heat30_frost1 "int_climate__window_indicators+" '{heat_tmax_threshold_c: 30, frost_tmin_threshold_c: 1}'; metrics heat30_frost1
run_chain heat34_frost3 "int_climate__window_indicators+" '{heat_tmax_threshold_c: 34, frost_tmin_threshold_c: 3}'; metrics heat34_frost3
reseed_windows 1; run_chain shift1 "int_climate__window_indicators+" '{}'; metrics shift1
reseed_windows 3; run_chain shift3 "int_climate__window_indicators+" '{}'; metrics shift3
reseed_windows 2; run_chain restore_defaults "int_climate__window_indicators+" '{}'; metrics restored
echo "DONE"
