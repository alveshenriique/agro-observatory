"""Compare two exported data versions file by file (for example BigQuery against Postgres).

Usage: uv run python scripts/compare_serving_bundles.py <folder A> <folder B>

Every published file must exist in both folders with the same structure. What differs by
nature between the two exports is ignored: the `meta` blocks (generation time), the
catalog's `warehouse`, the `dbt_tests` summary of method.json (each warehouse runs its own
tests; BigQuery has fewer because the daily-climate nodes are disabled there) and the
manifest. Text, integers, booleans and nulls
must be identical; a decimal number may differ by at most one unit in its last published
decimal place (the warehouses round the same decimals, but the climate indicators rebuilt on
Postgres can move the last bit of a float sum, which can flip a rounding). Exit code 1 if
anything else differs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def decimals(value: float) -> int:
    text = repr(value)
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


IGNORED_KEYS = {"meta", "warehouse", "dbt_tests"}


def compare(a, b, where: str, out: list[str], stats: dict) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            out.append(f"{where}: keys differ {sorted(set(a) ^ set(b))[:5]}")
            return
        for k in a:
            if k not in IGNORED_KEYS:
                compare(a[k], b[k], f"{where}.{k}", out, stats)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{where}: lengths {len(a)} != {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            compare(x, y, f"{where}[{i}]", out, stats)
    elif a == b and type(a) is type(b):
        return
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        step = 10.0 ** -max(decimals(float(a)), decimals(float(b)), 0)
        if abs(a - b) <= step + 1e-12:
            stats["last_digit"] += 1
        else:
            out.append(f"{where}: {a} != {b}")
    else:
        out.append(f"{where}: {a!r} != {b!r}")


def main(argv: list[str]) -> int:
    first, second = Path(argv[0]), Path(argv[1])
    files_a = {p.relative_to(first).as_posix() for p in first.rglob("*.json")} - {"manifest.json"}
    files_b = {p.relative_to(second).as_posix() for p in second.rglob("*.json")} - {"manifest.json"}
    problems = [f"only in one folder: {p}" for p in sorted(files_a ^ files_b)]
    stats = {"last_digit": 0}
    for path in sorted(files_a & files_b):
        a = json.loads((first / path).read_text())
        b = json.loads((second / path).read_text())
        out: list[str] = []
        compare(a, b, path, out, stats)
        problems.extend(out[:5])
    compared, last_digit = len(files_a & files_b), stats["last_digit"]
    print(f"{compared} files compared; {last_digit} values differ in the last digit")
    for p in problems[:50]:
        print("DIFF", p)
    print("bundles agree" if not problems else f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
