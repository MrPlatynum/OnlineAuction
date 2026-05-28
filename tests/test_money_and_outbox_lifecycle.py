"""Unit tests for the money conversion helpers and the email-outbox
worker lifecycle. Two tiny modules, both previously uncovered on the
edge cases (None passthrough, the ``start/stop`` idempotency, the
disabled-by-env short circuit). Direct unit drive, no DB or SMTP."""

import asyncio
from decimal import Decimal

import pytest

from app.services import email_outbox as outbox
from app.utils.money import money_to_float, quantize_money, to_decimal

# ---------------------------------------------------------------------
# money helpers
# ---------------------------------------------------------------------

def test_to_decimal_passes_through_none():
    assert to_decimal(None) is None


def test_to_decimal_routes_non_decimal_through_str():
    """Float / int / str inputs go through ``str`` to dodge IEEE-754
    rounding (``Decimal(0.1)`` ≠ ``Decimal('0.1')``)."""
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(7) == Decimal("7")
    assert to_decimal("3.14") == Decimal("3.14")


def test_to_decimal_returns_existing_decimal_unchanged():
    d = Decimal("12.34")
    assert to_decimal(d) is d


def test_quantize_money_rounds_half_up():
    """The boundary case `.005` must round UP under banker-free
    ROUND_HALF_UP, not down via Python's default banker rounding."""
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


def test_money_to_float_handles_none_and_decimal():
    assert money_to_float(None) is None
    assert money_to_float(Decimal("7.50")) == 7.5


# ---------------------------------------------------------------------
# outbox worker start/stop lifecycle
# ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_outbox_module_state():
    """The outbox worker uses module-level ``_worker_task`` /
    ``_stop_event`` - leakage across tests would cause the second
    start_outbox_worker call to short-circuit on an unrelated task
    from the previous test."""
    outbox._worker_task = None
    outbox._stop_event = None
    yield
    outbox._worker_task = None
    outbox._stop_event = None


async def test_start_outbox_worker_short_circuits_when_disabled(monkeypatch):
    """conftest sets AUCTION_OUTBOX_WORKER_ENABLED=false for the whole
    suite; verify the env-gated branch returns without spawning a task."""
    monkeypatch.setenv("AUCTION_OUTBOX_WORKER_ENABLED", "false")
    outbox.start_outbox_worker()
    assert outbox._worker_task is None


async def test_start_outbox_worker_skips_when_already_running(monkeypatch):
    """Second call to start_outbox_worker on an already-live task must
    be a no-op - calling create_app twice in a test process should
    not produce duplicate workers."""
    monkeypatch.setenv("AUCTION_OUTBOX_WORKER_ENABLED", "true")
    # Patch the actual tick to be a no-op forever (until stop_event fires)
    # so the worker stays "running" without doing DB work.
    async def _noop_tick():
        return 0
    monkeypatch.setattr(outbox, "_run_one_tick", _noop_tick)

    outbox.start_outbox_worker()
    first_task = outbox._worker_task
    assert first_task is not None

    outbox.start_outbox_worker()
    assert outbox._worker_task is first_task  # same task, not replaced

    await outbox.stop_outbox_worker()


async def test_outbox_worker_loop_starts_and_stops_cleanly(monkeypatch):
    """End-to-end: start the loop, let one tick run, then stop. The
    stop_event-driven wait exits promptly rather than waiting out the
    full WORKER_TICK_SECONDS."""
    monkeypatch.setenv("AUCTION_OUTBOX_WORKER_ENABLED", "true")
    # Short tick so the wait_for inside _worker_loop returns quickly.
    monkeypatch.setattr(outbox, "WORKER_TICK_SECONDS", 0.05)
    ticks = {"n": 0}
    async def _counting_tick():
        ticks["n"] += 1
        return 0
    monkeypatch.setattr(outbox, "_run_one_tick", _counting_tick)

    outbox.start_outbox_worker()
    assert outbox._worker_task is not None
    # Yield long enough for at least one tick to run.
    await asyncio.sleep(0.15)
    await outbox.stop_outbox_worker()
    assert outbox._worker_task is None
    assert ticks["n"] >= 1, "worker_loop must have iterated at least once"


async def test_outbox_worker_loop_survives_tick_failure(monkeypatch):
    """A tick that raises must be logged and the loop must keep ticking -
    one bad batch should not silently kill outbox delivery for the
    whole process."""
    monkeypatch.setenv("AUCTION_OUTBOX_WORKER_ENABLED", "true")
    monkeypatch.setattr(outbox, "WORKER_TICK_SECONDS", 0.05)
    calls = {"n": 0}
    async def _exploding_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated tick crash")
        return 0
    monkeypatch.setattr(outbox, "_run_one_tick", _exploding_tick)

    outbox.start_outbox_worker()
    await asyncio.sleep(0.2)
    await outbox.stop_outbox_worker()
    assert calls["n"] >= 2, "second tick must run despite first raising"
