"""HTTP load test for the auction API.

Spins up ``--concurrency`` async workers that share an ``httpx``
client and hammer the chosen endpoint with ``--requests`` calls in
total. Reports throughput (req/s) and latency percentiles.

Usage:
    python benchmarks/load_test.py
    python benchmarks/load_test.py --endpoint /api/auctions --requests 2000 --concurrency 100
    python benchmarks/load_test.py --base-url http://localhost:8000
"""

import argparse
import asyncio
import statistics
import time
from collections.abc import Callable

import httpx


async def _worker(
    client: httpx.AsyncClient,
    endpoint: str,
    take_request: Callable[[], int | None],
    latencies: list[float],
    errors: list[int],
) -> None:
    while True:
        idx = take_request()
        if idx is None:
            return
        start = time.perf_counter()
        try:
            response = await client.get(endpoint)
            elapsed = time.perf_counter() - start
            if response.status_code >= 400:
                errors.append(response.status_code)
            else:
                latencies.append(elapsed)
        except Exception:
            errors.append(-1)


def _make_request_taker(total: int) -> Callable[[], int | None]:
    counter = {"i": 0}

    def take_request() -> int | None:
        if counter["i"] >= total:
            return None
        counter["i"] += 1
        return counter["i"]

    return take_request


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(len(sorted_values) * pct / 100)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


async def run_benchmark(base_url: str, endpoint: str, requests: int, concurrency: int) -> None:
    print(
        f"Target:       {base_url}{endpoint}\n"
        f"Total reqs:   {requests}\n"
        f"Concurrency:  {concurrency}\n"
    )

    take_request = _make_request_taker(requests)
    latencies: list[float] = []
    errors: list[int] = []

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=30.0) as client:
        # Warm-up — 5 throwaway requests so the first measured request
        # doesn't pay TCP/handshake costs that skew percentiles.
        for _ in range(5):
            try:
                await client.get(endpoint)
            except Exception:
                pass

        wall_start = time.perf_counter()
        await asyncio.gather(*(
            _worker(client, endpoint, take_request, latencies, errors)
            for _ in range(concurrency)
        ))
        wall_elapsed = time.perf_counter() - wall_start

    completed = len(latencies)
    rps = completed / wall_elapsed if wall_elapsed > 0 else 0
    print(f"Completed:    {completed} / {requests}")
    print(f"Errors:       {len(errors)}")
    print(f"Wall time:    {wall_elapsed:.2f}s")
    print(f"Throughput:   {rps:.1f} req/s")
    if latencies:
        print(
            f"Latency (ms): "
            f"min={min(latencies)*1000:.1f}  "
            f"avg={statistics.mean(latencies)*1000:.1f}  "
            f"p50={_percentile(latencies, 50)*1000:.1f}  "
            f"p95={_percentile(latencies, 95)*1000:.1f}  "
            f"p99={_percentile(latencies, 99)*1000:.1f}  "
            f"max={max(latencies)*1000:.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--endpoint", default="/api/auctions")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.base_url, args.endpoint, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
