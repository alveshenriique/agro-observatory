"""Download IBGE's municipal mesh (polygons of every municipality) as GeoJSON.

The file is kept exactly as returned by the API (raw layer). It is used to aggregate gridded
climate data to municipalities; the maximum quality is used because the simplified meshes
distort small municipalities (up to 87% area difference in the minimum quality).
"""

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MESH_URL = (
    "https://servicodados.ibge.gov.br/api/v4/malhas/paises/BR"
    "?intrarregiao=municipio&formato=application/vnd.geo+json&qualidade=maxima"
)
DEFAULT_MESH_PATH = Path("data/raw/ibge_mesh/municipalities.geojson")


def download_mesh(path: Path = DEFAULT_MESH_PATH, force: bool = False) -> Path:
    if path.exists() and not force:
        logger.info("%s: already downloaded", path)
        return path

    response = httpx.get(MESH_URL, timeout=300, follow_redirects=True)
    response.raise_for_status()
    features = response.json().get("features", [])
    if not features or "codarea" not in features[0].get("properties", {}):
        raise ValueError("unexpected mesh response: no features with 'codarea'")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".geojson.tmp")
    tmp_path.write_bytes(response.content)
    os.replace(tmp_path, path)
    logger.info("%s: %d municipalities", path, len(features))
    return path


def read_mesh(path: Path = DEFAULT_MESH_PATH) -> dict[int, dict]:
    """Municipality id -> GeoJSON geometry."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    return {int(f["properties"]["codarea"]): f["geometry"] for f in features}
