"""Package an exported data version as a GitHub release asset (does not publish anything).

Usage (from the repository root):
    uv run package-serving dist/site-data/<version> [--out dist]

Checks the exported folder against its manifest (every file present with the recorded
sha256, every check ok, not the CI sample, exported from BigQuery unless --allow-postgres),
then writes:
- dist/site-data-<version>.tar.gz: the folder <version>/ in a reproducible tar (sorted
  entries, fixed timestamps and owners), the asset of the release `data-v<version>`;
- dist/release-notes-<version>.md: the release description;
- data-release.json (repository root): the pointer the site build reads to download and
  verify this version. It is committed; the release itself is created by hand, after review:
      gh release create data-v<version> <tarball> <manifest> --title ... --notes-file ...
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

POINTER = Path("data-release.json")
REPOSITORY = "alveshenriique/agro-observatory"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(folder: Path, allow_postgres: bool) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    problems = []
    if manifest["sample"]:
        problems.append("this is the CI sample")
    if manifest["warehouse"] != "bigquery" and not allow_postgres:
        problems.append(f"exported from {manifest['warehouse']}, not from the production warehouse")
    failed = [c["name"] for c in manifest["checks"] if c["status"] != "ok"]
    if failed:
        problems.append(f"failed checks: {failed}")
    listed = {f["path"] for f in manifest["files"]}
    on_disk = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} - {
        "manifest.json"
    }
    if listed != on_disk:
        problems.append(f"files differ from the manifest: {sorted(listed ^ on_disk)[:5]}")
    for f in manifest["files"]:
        path = folder / f["path"]
        if path.exists() and sha256(path) != f["sha256"]:
            problems.append(f"{f['path']}: sha256 differs from the manifest")
    if problems:
        raise SystemExit("cannot package: " + "; ".join(problems))
    return manifest


def tarball(folder: Path, target: Path) -> None:
    """A reproducible .tar.gz: same files, same bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            info = tarfile.TarInfo(f"{folder.name}/{path.relative_to(folder).as_posix()}")
            data = path.read_bytes()
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    target.write_bytes(gzip.compress(buffer.getvalue(), 9, mtime=0))


CHECKS_PT = {
    "explore matrices equal the fact table": (
        "Matrizes do Explorar iguais ao fato de produção: somas, contagens, zeros e nulos por "
        "série, medida e ano."
    ),
    "territorial files add up": (
        "Fichas territoriais consistentes: Brasil igual ao fato; UFs, macrorregiões e regiões "
        "imediatas somam o Brasil; cada região imediata soma os seus municípios."
    ),
    "main finding matches the association mart": (
        "Achado principal igual ao recalculado a partir do mart de associação clima × rendimento."
    ),
    "climate rows equal the association mart": (
        "Linhas de clima das fichas de UF e de região imediata iguais às do mart de associação."
    ),
    "mesh decodes to a valid coverage of the index": (
        "Malha decodificada como cobertura válida, com exatamente os municípios do índice; as "
        "malhas por UF particionam a nacional."
    ),
}
WAREHOUSES = {"bigquery": "BigQuery", "postgres": "PostgreSQL"}


def number(value: float, digits: int = 1) -> str:
    """Portuguese formatting: 1.234,5."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def percent(fraction: float, signed: bool = False) -> str:
    text = number(100 * fraction) + "%"
    return ("+" + text if fraction > 0 else text.replace("-", "−")) if signed else text


def notes(folder: Path, manifest: dict, version: str, asset: str, digest: str, size: int) -> str:
    files = manifest["files"]
    total = sum(f["bytes"] for f in files)
    total_gz = sum(f["gzip_bytes"] for f in files)
    commit = (manifest["git"]["commit"] or "desconhecido")[:7]
    when = manifest["meta"]["generated_at"].replace("T", " às ").replace("Z", " UTC")
    lines = [
        f"Pacote de dados do site, versão {version}.",
        "",
        f"Gerado em {when} a partir do "
        f"{WAREHOUSES.get(manifest['warehouse'], manifest['warehouse'])}, no commit {commit}. "
        f"São {len(files) + 1} arquivos: {number(total / 2**20)} MiB sem compressão e "
        f"{number(total_gz / 2**20)} MiB com gzip. O contrato dos arquivos (esquemas, significado "
        "de cada valor e regras para o site) está em docs/CONTRATO_DE_DADOS.md.",
    ]
    analysis_path, method_path = folder / "analysis.json", folder / "method.json"
    headline = json.loads(analysis_path.read_text())["headline"] if analysis_path.exists() else None
    if headline and headline["state_years"]:
        lines += [
            "",
            "**Achado principal (soja).** "
            f"Nos {headline['state_years']} UF-anos com normal climatológica e tendência "
            f"({headline['first_year']}–{headline['last_year']}), a anomalia média de rendimento "
            f"foi de {percent(headline['mean_anomaly_water_deficit_years'], True)} nos anos de "
            f"seca na floração e enchimento, contra "
            f"{percent(headline['mean_anomaly_other_years'], True)} nos demais; "
            f"{percent(headline['below_trend_share_water_deficit_years'])} dos anos de seca "
            f"ficaram abaixo da tendência, contra "
            f"{percent(headline['below_trend_share_all_years'])} dos anos em geral. A correlação "
            "entre balanço hídrico e anomalia é positiva em "
            f"{headline['regions_with_positive_correlation']} das "
            f"{headline['regions_with_correlation']} regiões imediatas com série. Associação, "
            "não causalidade.",
        ]
    if method_path.exists():
        method = json.loads(method_path.read_text())
        validation = method["validation"]
        cells = dict.fromkeys(("match", "documented", "mismatch"), 0)
        for status, n in zip(
            validation["sidra_summary"]["status"], validation["sidra_summary"]["cells"], strict=True
        ):
            cells[status] += n
        scope = dict(
            zip(
                validation["sidra_scope"]["category"],
                validation["sidra_scope"]["cells"],
                strict=True,
            )
        )
        grid = sum(scope.values())
        conab = validation["conab"]
        compared = sum(bool(v) for v in conab["is_compared"])
        beyond = sum(bool(v) for v in conab["is_beyond_tolerance"])
        lines += [
            "",
            "**Validação.**",
            f"- IBGE (agregados Brasil e UF da tabela 5457): {number(scope['compared'], 0)} "
            f"células comparadas, {number(cells['match'], 0)} iguais, {cells['documented']} "
            f"diferenças da própria fonte documentadas com o motivo e {cells['mismatch']} "
            f"divergências. A grade baixada tem {number(grid, 0)} combinações, das quais "
            f"{number(grid - scope['compared'], 0)} não têm valor publicado. "
            f"{validation['sidra_definition_pt']}",
            f"- Conab (soja por UF, desde 2010, outro método): {compared} UF-anos comparados, "
            f"{beyond} com diferença acima de 10% (aviso).",
        ]
        tests = method["dbt_tests"]
        if tests:
            lines.append(
                f"- Testes do dbt no {WAREHOUSES.get(manifest['warehouse'])}: {tests['pass']} "
                f"aprovados, {tests['warn']} avisos conhecidos, {tests['error'] + tests['fail']} "
                "falhas."
            )
    lines += ["", "**Conciliação dos arquivos com os marts** (todas aprovadas):"]
    lines += [f"- {CHECKS_PT.get(c['name'], c['name'])}" for c in manifest["checks"]]
    lines += [
        "",
        f"Arquivo: `{asset}` ({number(size / 2**20)} MiB), sha256 `{digest}`. O ponteiro "
        "`data-release.json` no repositório fixa esta versão para o build do site.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="package-serving", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "folder", type=Path, help="exported version folder, e.g. dist/site-data/2026.11.07"
    )
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--pointer", type=Path, default=POINTER)
    parser.add_argument("--allow-postgres", action="store_true", help="for local tests only")
    args = parser.parse_args(argv)

    manifest = verify(args.folder, args.allow_postgres)
    version = manifest["meta"]["data_version"]
    if args.folder.name != version:
        raise SystemExit(f"folder {args.folder.name} does not match data version {version}")
    args.out.mkdir(parents=True, exist_ok=True)
    asset = f"site-data-{version}.tar.gz"
    target = args.out / asset
    tarball(args.folder, target)
    digest, size = sha256(target), target.stat().st_size
    notes_path = args.out / f"release-notes-{version}.md"
    notes_path.write_text(
        notes(args.folder, manifest, version, asset, digest, size), encoding="utf-8"
    )
    tag = f"data-v{version}"
    pointer = {
        "data_version": version,
        "release_tag": tag,
        "asset": asset,
        "asset_url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset}",
        "sha256": digest,
        "bytes": size,
        "manifest_sha256": sha256(args.folder / "manifest.json"),
        "schema_versions": sorted(
            {f"{f['schema']}/{f['schema_version']}" for f in manifest["files"]}
        ),
        "generated_at": manifest["meta"]["generated_at"],
        "warehouse": manifest["warehouse"],
        "commit": manifest["git"]["commit"],
    }
    args.pointer.write_text(
        json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {target} ({size / 2**20:.1f} MiB, sha256 {digest})")
    print(f"wrote {notes_path} and {args.pointer}")
    print("to publish (after review):")
    print(
        f"  gh release create {tag} {target} {args.folder / 'manifest.json'} "
        f"--title 'Dados do site {version}' --notes-file {notes_path} "
        f"--target {manifest['git']['commit']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
