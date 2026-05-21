#!/usr/bin/env bash
# Compare async (uvicorn) vs sync (gunicorn) throughput + memory on the
# same machine, same Postgres, same endpoint. Used to populate Table 4.5
# in the thesis - the value is the ratio, not the absolute number.
#
# Usage:
#   chmod +x benchmarks/compare_stacks.sh
#   benchmarks/compare_stacks.sh > /tmp/bench_results.txt
#
# Pre-requisites (one-time):
#   - .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
#   - .venv/bin/pip install flask gunicorn   # not in main requirements
#   - Postgres reachable at DATABASE_URL (see below)
#   - alembic upgrade head already applied
#   - At least a few seeded auctions (e.g. AUCTION_ENV=test python -m scripts.seed_demo_auctions)
set -u

# --- config ----------------------------------------------------------------
: "${DATABASE_URL:=postgresql+asyncpg://auction:auction_dev_password@localhost:5433/auction_test}"
: "${AUCTION_SECRET_KEY:=$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(64))')}"
: "${REQUESTS:=1000}"
: "${ASYNC_PORT:=8000}"
: "${SYNC_PORT:=8001}"
: "${WORKERS:=1 2 4 10}"
: "${CONCURRENCIES:=10 50 100}"
export DATABASE_URL AUCTION_SECRET_KEY
export AUCTION_ENV=test
export AUCTION_RATE_LIMIT_ENABLED=false
export AUCTION_SCHEDULER_ELECTION_ENABLED=false
export AUCTION_OUTBOX_WORKER_ENABLED=false
# Some XDG setups won't let gunicorn write its control socket - redirect.
export XDG_RUNTIME_DIR="/tmp"

PY=".venv/bin/python"
GUNI=".venv/bin/gunicorn"
UVI=".venv/bin/uvicorn"

# --- helpers ---------------------------------------------------------------
have_pg() {
  $PY -c "
import asyncio, asyncpg, sys
async def _():
    try:
        c = await asyncpg.connect('${DATABASE_URL/+asyncpg/}')
        await c.close()
    except Exception as e:
        sys.exit('cannot reach Postgres: ' + str(e))
asyncio.run(_())
"
}

kill_workers() {
  # Match only the venv-launched servers - not the script itself.
  ps -ef | grep -E "\.venv/bin/(gunicorn|uvicorn)" | grep -v grep \
    | awk '{print $2}' | xargs -r kill -9 2>/dev/null
  sleep 1
}

start_async() {
  $UVI app:app --host 127.0.0.1 --port "$ASYNC_PORT" \
      --workers 1 --log-level warning > /tmp/uvi.log 2>&1 &
  sleep 4
  curl -sf "http://127.0.0.1:$ASYNC_PORT/api/auctions" > /dev/null \
    || { echo "  ! async smoke failed"; return 1; }
}

start_sync() {
  local w=$1
  $GUNI -w "$w" -b "127.0.0.1:$SYNC_PORT" --log-level warning \
      benchmarks.sync_baseline:app > /tmp/guni.log 2>&1 &
  sleep 4
  curl -sf "http://127.0.0.1:$SYNC_PORT/api/auctions" > /dev/null \
    || { echo "  ! sync smoke failed"; return 1; }
}

memory_rss_mb() {
  # Sum RSS (KB) of all matching processes -> MB
  ps -eo rss,cmd | grep -E "\.venv/bin/(gunicorn|uvicorn)" | grep -v grep \
    | awk '{s+=$1} END {printf "%.1f", s/1024}'
}

bench() {
  local base=$1
  for c in $CONCURRENCIES; do
    echo "    conc=$c:"
    $PY benchmarks/load_test.py --base-url "$base" \
        --endpoint /api/auctions --requests "$REQUESTS" --concurrency "$c" \
        2>&1 | grep -E "Throughput|Latency|Errors" | sed 's/^/      /'
  done
}

# --- main ------------------------------------------------------------------
echo "============================================================"
echo "STACK COMPARISON  ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo "============================================================"
echo "Host:        $(uname -a)"
echo "CPU:         $(grep -c ^processor /proc/cpuinfo) logical cores"
echo "RAM total:   $(free -h | awk '/^Mem:/ {print $2}')"
echo "Python:      $($PY --version 2>&1)"
echo "Postgres:    $(echo "$DATABASE_URL" | sed 's|.*@||')"
echo "Requests:    $REQUESTS"
echo "Concurrencies: $CONCURRENCIES"
echo "Sync workers to test: $WORKERS"
echo

echo ">>> sanity check: Postgres reachable, has data"
have_pg
n=$($PY -c "
import asyncio, asyncpg
async def _():
    c = await asyncpg.connect('${DATABASE_URL/+asyncpg/}')
    print(await c.fetchval('select count(*) from auctions where is_active'))
    await c.close()
asyncio.run(_())
")
echo "  active auctions in DB: $n"
if [ "$n" -lt 10 ]; then
  echo "  ! warning: low auction count - throughput may be unrealistically high"
fi
kill_workers

echo
echo "============================================================"
echo "ASYNC: uvicorn 1 worker"
echo "============================================================"
start_async || exit 1
sleep 1
echo "  RSS: $(memory_rss_mb) MB"
bench "http://127.0.0.1:$ASYNC_PORT"
kill_workers

for w in $WORKERS; do
  echo
  echo "============================================================"
  echo "SYNC: gunicorn $w workers"
  echo "============================================================"
  start_sync "$w" || { kill_workers; continue; }
  sleep 1
  echo "  RSS: $(memory_rss_mb) MB"
  bench "http://127.0.0.1:$SYNC_PORT"
  kill_workers
done

echo
echo "============================================================"
echo "DONE - copy this entire output to send back"
echo "============================================================"
