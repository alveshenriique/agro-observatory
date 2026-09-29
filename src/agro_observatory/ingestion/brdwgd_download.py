"""Download the BR-DWGD NetCDF files needed by the project.

BR-DWGD (Xavier et al., 2022) is distributed as large zips on Google Drive, each holding
several variables. Only 4 variables are used (pr, Tmax, Tmin, ETo), so instead of downloading
whole zips, the zip index is read with HTTP Range requests and only the needed members are
streamed and decompressed to disk. Files already on disk with the expected size are skipped.

Every file is checked against the SHA-256 manifest versioned in the repository
(checksums/brdwgd_v3.2.4.sha256, in `sha256sum` format); a missing or different hash fails
the ingestion, so a silent change in the source cannot slip into the data.
"""

import hashlib
import io
import logging
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DRIVE_URL = "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
DEFAULT_NETCDF_DIR = Path("data/external/brdwgd")
VARIABLES = ("pr", "Tmax", "Tmin", "ETo")
SOURCE_VERSION = "v_3.2.4"  # as written by the source (file names, author page)
CHECKSUMS_PATH = Path("checksums/brdwgd_v3.2.4.sha256")


class ChecksumError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksums(path: Path = CHECKSUMS_PATH) -> dict[str, str]:
    """File name -> expected SHA-256, from a `sha256sum` output file."""
    checksums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            checksums[name.lstrip("*")] = digest
    return checksums


def verify_checksum(path: Path, checksums: dict[str, str], name: str | None = None) -> None:
    """Fail if the file's SHA-256 differs from the manifest (`name` defaults to the file's)."""
    name = name or path.name
    expected = checksums.get(name)
    if expected is None:
        raise ChecksumError(f"{name} is not in the checksum manifest")
    actual = sha256_file(path)
    if actual != expected:
        raise ChecksumError(f"{name}: SHA-256 {actual} does not match the manifest ({expected})")


@dataclass(frozen=True)
class RemoteZip:
    name: str
    file_id: str


# Google Drive file ids from the official download folder (see README.txt in that folder).
REMOTE_ZIPS = (
    RemoteZip("pr_Tmax_Tmin_NetCDF_Files.zip", "1oQWHpXwFgTKNH4Fa2GwCPJ3QN1AMgNPJ"),
    RemoteZip("ETo_u2_RH_Rs_NetCDF_Files.zip", "1aGdOHRT10W8oBWvE5IvmEAqJCNQOYYid"),
)


class HttpRangeFile(io.RawIOBase):
    """Read-only, seekable file over HTTP Range requests (enough for zipfile)."""

    def __init__(self, client: httpx.Client, url: str) -> None:
        self._client = client
        self._url = url
        self._pos = 0
        response = client.get(url, headers={"Range": "bytes=0-0"})
        response.raise_for_status()
        self._size = int(response.headers["Content-Range"].rsplit("/", 1)[1])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = base + offset
        return self._pos

    def readinto(self, buffer) -> int:
        size = min(len(buffer), self._size - self._pos)
        if size <= 0:
            return 0
        end = self._pos + size - 1
        response = self._client.get(self._url, headers={"Range": f"bytes={self._pos}-{end}"})
        response.raise_for_status()
        data = response.content
        buffer[: len(data)] = data
        self._pos += len(data)
        return len(data)


def is_needed(member_name: str) -> bool:
    return Path(member_name).name.split("_")[0] in VARIABLES


def download_netcdf_files(
    output_dir: Path = DEFAULT_NETCDF_DIR, checksums_path: Path = CHECKSUMS_PATH
) -> list[Path]:
    checksums = read_checksums(checksums_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        for remote in REMOTE_ZIPS:
            url = DRIVE_URL.format(file_id=remote.file_id)
            raw = io.BufferedReader(HttpRangeFile(client, url), buffer_size=16 * 1024 * 1024)
            with zipfile.ZipFile(raw) as archive:
                for member in archive.infolist():
                    if not is_needed(member.filename):
                        continue
                    path = output_dir / Path(member.filename).name
                    paths.append(path)
                    if path.exists() and path.stat().st_size == member.file_size:
                        logger.info("%s: already downloaded", path.name)
                        continue
                    logger.info(
                        "%s: downloading %.2f GB (%.2f GB on disk)",
                        path.name,
                        member.compress_size / 1e9,
                        member.file_size / 1e9,
                    )
                    tmp_path = path.with_suffix(".nc.tmp")
                    with archive.open(member) as source, tmp_path.open("wb") as target:
                        while chunk := source.read(16 * 1024 * 1024):
                            target.write(chunk)
                    # Checked before the rename, so a corrupt file never gets the final name.
                    verify_checksum(tmp_path, checksums, name=path.name)
                    os.replace(tmp_path, path)
    return paths
