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
