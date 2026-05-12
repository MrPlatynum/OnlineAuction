"""Content-Security-Policy regression tests.

The CSP we ship blocks inline ``<script>`` blocks and inline event
handlers (``script-src 'self'`` with no ``'unsafe-inline'``). The
test suite asserts both halves:

* every served HTML page actually carries the policy header,
* no template still contains ``onclick=``/``onchange=``/``oninput=`` or
  an inline ``<script>...</script>`` block — anything that did would
  silently break under the policy.
"""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob("*.html"))

_INLINE_HANDLER_RE = re.compile(
    r"\bon(click|change|input|submit|keydown|keyup|focus|blur|"
    r"mouseover|mouseout|mouseenter|mouseleave|load)\s*=",
    re.IGNORECASE,
)
# Match real inline-content <script> blocks. A ``<script src="…">`` tag
# with no body is fine — those are loaded from same-origin under
# ``script-src 'self'`` — so the pattern explicitly excludes them.
_INLINE_SCRIPT_RE = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", re.IGNORECASE
)


@pytest.mark.parametrize(
    "path",
    [pytest.param(p, id=p.name) for p in TEMPLATE_FILES],
)
def test_template_has_no_inline_handlers(path: Path):
    """No ``onclick=``/``onchange=``/``oninput=`` attributes survive in
    rendered templates. Inline handlers are blocked by ``script-src
    'self'`` so any straggler would silently break the page."""
    body = path.read_text(encoding="utf-8")
    matches = _INLINE_HANDLER_RE.findall(body)
    assert not matches, (
        f"{path.name} still carries inline event handler(s): "
        f"{matches[:3]}{'…' if len(matches) > 3 else ''}"
    )


@pytest.mark.parametrize(
    "path",
    [pytest.param(p, id=p.name) for p in TEMPLATE_FILES],
)
def test_template_has_no_inline_script_blocks(path: Path):
    """Inline ``<script>...</script>`` blocks would be blocked too —
    everything has to come in via ``<script src="...">`` from same
    origin. External script tags (``src=`` set) are fine."""
    body = path.read_text(encoding="utf-8")
    bodies = _INLINE_SCRIPT_RE.findall(body)
    # Filter out empty matches and pure whitespace.
    real = [b for b in bodies if b.strip()]
    assert not real, (
        f"{path.name} still has an inline <script> block (length "
        f"{[len(b) for b in real]}); move it to a static/js/*.js file."
    )


async def test_csp_header_present_on_html_response(client):
    """Every page served by the static-pages router carries the
    policy header. We probe the root document to confirm the
    middleware is wired and producing the expected value."""
    r = await client.get("/")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    # ``script-src 'self'`` with no ``'unsafe-inline'`` is the whole
    # point of this PR; assert the absence explicitly so a future
    # loosening can't slip in by accident.
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "frame-ancestors 'none'" in csp


async def test_csp_header_present_on_api_response(client):
    """The middleware applies to API responses too — useful so that an
    attacker who tricks a victim into navigating directly to an API
    endpoint that happens to render attacker-controlled JSON still
    can't get script execution from it."""
    r = await client.get("/api/auctions?page=1&page_size=1")
    assert r.status_code == 200
    assert "content-security-policy" in {k.lower() for k in r.headers.keys()}


def test_per_page_js_files_resolve_under_same_origin():
    """All ``<script src=...>`` tags in templates point at
    ``/static/...`` or ``/static/vendor/...`` — same-origin under the
    policy. If any page started linking a third-party CDN we'd need
    to widen ``script-src``, so failing this test is a flag to
    revisit the policy intentionally."""
    static_dir = Path(__file__).resolve().parent.parent / "static"
    script_src_re = re.compile(
        r'<script[^>]*\bsrc="([^"]+)"', re.IGNORECASE
    )
    bad: list[str] = []
    for template in TEMPLATE_FILES:
        for src in script_src_re.findall(template.read_text(encoding="utf-8")):
            if src.startswith("http://") or src.startswith("https://"):
                bad.append(f"{template.name}: {src}")
                continue
            # Must resolve under /static or /static/vendor.
            if not src.startswith("/static/"):
                bad.append(f"{template.name}: {src}")
                continue
            rel = src[len("/static/"):]
            if not (static_dir / rel).exists():
                bad.append(f"{template.name}: {src} (file missing)")
    assert not bad, "Same-origin policy violations: " + ", ".join(bad)
