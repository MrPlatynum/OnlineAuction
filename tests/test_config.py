"""Config invariants.

These are environment-defensive defaults: tests run without
``AUCTION_ENV`` set, so dev-only conveniences must be off in this
session - anything that would loosen the security posture in prod
should fail the same way under test.
"""


def test_local_cors_regex_off_when_env_unset():
    """``LOCAL_CORS_REGEX`` lights up the localhost-CORS escape hatch.
    It must be ``None`` unless the operator explicitly opts in via
    ``AUCTION_ENV=dev/local/test`` - otherwise an attacker hosting a
    page on a fake ``localhost`` subdomain (or via /etc/hosts) could
    make credentialed cross-origin calls to a production deployment."""
    from app.config import LOCAL_CORS_REGEX

    assert LOCAL_CORS_REGEX is None


def test_commission_percent_rejects_out_of_range(monkeypatch):
    """A typo like ``PLATFORM_COMMISSION_PERCENT=70`` (meant 7.0) or a
    negative value used to silently corrupt every settle from then
    on, since nothing downstream re-checks the constant. The loader
    now raises at module load if the value is outside [0, 100]."""
    from app import config as cfg_mod

    monkeypatch.setenv("PLATFORM_COMMISSION_PERCENT", "150")
    try:
        cfg_mod._load_commission_percent()
    except RuntimeError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for out-of-range commission")

    monkeypatch.setenv("PLATFORM_COMMISSION_PERCENT", "-1")
    try:
        cfg_mod._load_commission_percent()
    except RuntimeError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for negative commission")


def test_commission_percent_rejects_garbage(monkeypatch):
    from app import config as cfg_mod

    monkeypatch.setenv("PLATFORM_COMMISSION_PERCENT", "seven")
    try:
        cfg_mod._load_commission_percent()
    except RuntimeError as exc:
        assert "valid decimal" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for non-decimal commission")
