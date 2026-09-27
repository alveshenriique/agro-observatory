import httpx
import pytest

from agro_observatory.http_client import HttpClient


def make_client(responses: list[httpx.Response], sleeps: list[float]) -> HttpClient:
    queue = iter(responses)
    transport = httpx.MockTransport(lambda request: next(queue))
    return HttpClient(transport=transport, max_retries=2, min_interval=0, sleep=sleeps.append)


def test_retries_with_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    client = make_client(
        [httpx.Response(503), httpx.Response(500), httpx.Response(200, json=[1])], sleeps
    )

    assert client.get_json("http://example") == [1]
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_max_retries() -> None:
    client = make_client([httpx.Response(503)] * 3, [])

    with pytest.raises(RuntimeError, match="giving up after 3 attempts"):
        client.get_json("http://example")


def test_does_not_retry_client_errors() -> None:
    sleeps: list[float] = []
    client = make_client([httpx.Response(400)], sleeps)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("http://example")
    assert sleeps == []
