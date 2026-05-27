#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "httpx>=0.28",
# ]
# ///
"""Check generated URL entries and report anything that is not HTTP 200."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URLS = ROOT / "json" / "urls.json"
USER_AGENT = "Awesome-llms-txt-url-check/1.0"


@dataclass(frozen=True)
class Result:
    url: str
    status: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


def load_urls(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(url, str) for url in data):
        raise ValueError(f"{path} must contain a JSON array of strings")
    return data


async def check_url(client: httpx.AsyncClient, url: str) -> Result:
    try:
        response = await client.head(url)
        if response.status_code in {405, 501}:
            response = await client.get(url)
        return Result(url=url, status=response.status_code)
    except httpx.HTTPError as exc:
        return Result(url=url, status=None, error=f"{type(exc).__name__}: {exc}")


async def worker(
    queue: asyncio.Queue[str],
    results: list[Result],
    client: httpx.AsyncClient,
) -> None:
    while True:
        try:
            url = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        result = await check_url(client, url)
        results.append(result)
        if not result.ok:
            detail = result.status if result.status is not None else result.error
            print(f"{detail}\t{result.url}", flush=True)
        queue.task_done()


async def check_urls(
    urls: list[str],
    workers: int,
    timeout: float,
    follow_redirects: bool,
) -> list[Result]:
    queue: asyncio.Queue[str] = asyncio.Queue()
    for url in urls:
        queue.put_nowait(url)

    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
    timeout_config = httpx.Timeout(timeout)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.8"}

    async with httpx.AsyncClient(
        follow_redirects=follow_redirects,
        headers=headers,
        limits=limits,
        timeout=timeout_config,
    ) as client:
        results: list[Result] = []
        tasks = [
            asyncio.create_task(worker(queue, results, client)) for _ in range(workers)
        ]
        await queue.join()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch generated URLs concurrently and report non-200 entries."
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_URLS)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--follow-redirects",
        action="store_true",
        help="follow redirects and judge the final response status",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    urls = load_urls(args.file)
    results = asyncio.run(
        check_urls(
            urls=urls,
            workers=args.workers,
            timeout=args.timeout,
            follow_redirects=args.follow_redirects,
        )
    )
    failures = [result for result in results if not result.ok]
    checked = len(results)

    print(
        f"checked {checked} URLs: {checked - len(failures)} ok, {len(failures)} failed",
        file=sys.stderr,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
