import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from agro_observatory.ingestion import pam
from agro_observatory.ingestion.common import InvalidResponseError
from agro_observatory.ingestion.pam import CROPS, Task

FIXTURE = Path(__file__).parent / "fixtures" / "sidra_pam_corn_2024.json"
CORN_2024 = Task(CROPS["corn"], 2024)


@pytest.fixture
def payload() -> list[dict[str, str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_build_url() -> None:
    assert pam.build_url(CROPS["coffee_arabica"], 2023) == (
        "https://apisidra.ibge.gov.br/values/t/5457/n6/all/v/8331,216,214,112,215/p/2023/c782/40140"
    )


def test_parse_response_drops_header_and_keeps_values_as_text(payload) -> None:
    rows = pam.parse_response(payload, CORN_2024)

    assert len(rows) == len(payload) - 1
    values = {row["V"] for row in rows}
    assert {"-", "..."} <= values
    assert all(isinstance(v, str) for v in values)


def test_parse_response_rejects_rows_from_another_year(payload) -> None:
    with pytest.raises(InvalidResponseError, match="does not match"):
        pam.parse_response(payload, Task(CROPS["corn"], 2023))


@pytest.mark.parametrize("bad", [[], {"erro": "x"}, [{"foo": "bar"}, {"foo": "1"}]])
def test_parse_response_rejects_malformed_payload(bad) -> None:
    with pytest.raises(InvalidResponseError):
        pam.parse_response(bad, CORN_2024)


def test_plan_tasks_respects_first_year_and_filters() -> None:
    tasks = pam.plan_tasks([CROPS["soybean"], CROPS["coffee_arabica"]], 2025, years=[2000, 2025])

    assert [(t.crop.slug, t.year) for t in tasks] == [
        ("soybean", 2000),
        ("soybean", 2025),
        ("coffee_arabica", 2025),
    ]
    assert len(pam.plan_tasks(CROPS.values(), 2025)) == 3 * 52 + 2 * 14


@pytest.mark.parametrize(
    ("year", "exists", "force", "expected"),
    [
        (2020, False, False, True),  # missing partition
        (2020, True, False, False),  # old partition already downloaded
        (2020, True, True, True),  # forced
        (2024, True, False, True),  # recent year: IBGE may have revised it
        (2025, True, False, True),
    ],
)
def test_should_download(year, exists, force, expected) -> None:
    assert pam.should_download(year, latest_year=2025, exists=exists, force=force) is expected


def test_run_is_idempotent(tmp_path, payload) -> None:
    calls: list[str] = []

    def fake_fetch(url: str):
        calls.append(url)
        return payload

    tasks = [CORN_2024]
    old_latest = 2030  # makes 2024 an "old" year, so it is skipped once it exists

    first = pam.run(tasks, fake_fetch, tmp_path, latest_year=old_latest)
    second = pam.run(tasks, fake_fetch, tmp_path, latest_year=old_latest)
    forced = pam.run(tasks, fake_fetch, tmp_path, latest_year=old_latest, force=True)
    recent = pam.run(tasks, fake_fetch, tmp_path, latest_year=2024)

    assert first["downloaded"] == 1
    assert second == {"downloaded": 0, "skipped": 1, "failed": 0}
    assert forced["downloaded"] == 1
    assert recent["downloaded"] == 1
    assert len(calls) == 3

    files = list(tmp_path.rglob("*.parquet*"))
    assert files == [tmp_path / "crop=corn" / "year=2024" / "data.parquet"]
    assert pq.read_table(files[0]).num_rows == len(payload) - 1


def test_run_keeps_going_after_a_failed_partition(tmp_path, payload) -> None:
    def flaky_fetch(url: str):
        if "/p/2023/" in url:
            raise RuntimeError("boom")
        return payload

    tasks = [Task(CROPS["corn"], 2023), CORN_2024]
    counts = pam.run(tasks, flaky_fetch, tmp_path, latest_year=2030)

    assert counts == {"downloaded": 1, "skipped": 0, "failed": 1}
    assert not (tmp_path / "crop=corn" / "year=2023").exists()
