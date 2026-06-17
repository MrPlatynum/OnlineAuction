# Notify fan-out microbenchmark

Sandbox box, PostgreSQL 16 in Docker on the same host (loopback),
fresh async session per call, WS push replaced with a no-op stub (the
database side is the architectural decision under test). The loop arm
restores the pre-PR-67 ``_fire_and_forget_email`` semantics via
monkeypatch so the historical second-SessionLocal-per-recipient cost
is reproduced honestly; the batch arm runs the current ``notify_many``.
Both arms run against the same seeded Auction so every Notification
row carries a real ``auction_id`` and PostgreSQL performs the same
foreign-key validation it would in production. 12 measured iterations
per row, 2 warm-up iterations discarded; loop and batch are measured
in consecutive blocks (not interleaved) so the per-path percentiles
are independent draws.

`loop` = pre-PR-67 `for u in users: await notify_user(...)`.
`batch` = current `await notify_many(db, payloads, ...)`.

| N recipients | loop mean | batch mean | Speed-up | Loop commits | Batch commits |
| ------------:| ---------:| ----------:| --------:| ------------:| -------------:|
|            5 |    850 ms |     162 ms |   5,2x   |           10 |             1 |
|           10 |  1 604 ms |     169 ms |   9,5x   |           20 |             1 |
|           20 |  2 988 ms |     181 ms |  16,6x   |           40 |             1 |
|           50 |  7 685 ms |     250 ms |  31 x    |          100 |             1 |
|          100 | 14 563 ms |     364 ms |  40 x    |          200 |             1 |

Reading:

- `loop` scales linearly at roughly 144 ms per recipient: one
  Notification commit on the caller's session plus a second
  SessionLocal open / outbox INSERT / commit dedicated to the email
  row.
- `batch` is dominated by the per-call fixed cost (acquire session,
  build payloads, two multi-row INSERTs - one per table, single
  COMMIT, refresh primary keys). Marginal cost of one extra recipient
  is around 2 ms even at N=100.
- The batch arm wins for every recipient count this benchmark
  supports - the cross-over sits below N=1 because the per-call
  overhead of the loop arm is dominated by the second SessionLocal
  roundtrip, not by Python work.

Reproduce:

```bash
docker compose up -d  # exposes Postgres on 5433
PYTHONPATH=. .venv/bin/python benchmarks/notify_fanout.py \
    --recipients 20 --iters 20
```
