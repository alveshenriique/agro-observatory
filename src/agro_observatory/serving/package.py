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


def notes(manifest: dict, version: str, asset: str, digest: str, size: int) -> str:
    files = manifest["files"]
    total = sum(f["bytes"] for f in files)
    total_gz = sum(f["gzip_bytes"] for f in files)
    checks = "\n".join(f"- {c['name']}: {c['detail']}" for c in manifest["checks"])
    return f"""Pacote de dados do site, versão {version}.

Gerado em {manifest["meta"]["generated_at"]} a partir do {manifest["warehouse"]} \
(commit {manifest["git"]["commit"]}), com {len(files) + 1} arquivos: {total / 2**20:.1f} MiB \
sem compressão, {total_gz / 2**20:.1f} MiB com gzip. O contrato dos arquivos está em \
docs/CONTRATO_DE_DADOS.md; cada arquivo tem esquema, versão dos dados, data de geração e fontes.

Checagens de conciliação com os marts:
{checks}

Arquivo: `{asset}` ({size / 2**20:.1f} MiB), sha256 `{digest}`. O ponteiro `data-release.json` \
no repositório fixa esta versão para o build do site.
"""


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
    notes_path.write_text(notes(manifest, version, asset, digest, size), encoding="utf-8")
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
        f"--title 'Dados do site {version}' --notes-file {notes_path} --target <commit>"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
