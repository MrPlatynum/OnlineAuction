"""Email template tests.

The notification HTML is built by string interpolation, which means
every user-controlled field (lot titles, usernames, message copy) has
to be HTML-escaped before it lands in the template — otherwise a
malicious lot title like ``<img src=x onerror=alert(1)>`` becomes
live HTML in whatever the recipient's mail client renders.
"""

from app.services.email import build_notification_email_html


def test_user_controlled_fields_are_html_escaped():
    out = build_notification_email_html(
        notification_type_value="auction_won",
        title="<img src=x onerror=alert(1)>",
        message='<script>alert("xss")</script>',
        auction_id=42,
        auction_title='evil " title <iframe>',
    )

    # No raw injected tags survive in the rendered template.
    assert "<img src=x" not in out
    assert "<script>" not in out
    assert "<iframe>" not in out
    assert 'evil " title' not in out

    # The escaped versions are what actually got rendered.
    assert "&lt;script&gt;" in out
    assert "&lt;iframe&gt;" in out
    assert "&lt;img" in out
    assert "&quot;" in out


def test_safe_strings_render_unchanged():
    """Non-malicious copy with cyrillic, emojis and currency markers
    should pass through ``html.escape`` without surprises."""
    out = build_notification_email_html(
        notification_type_value="auction_sold",
        title="💰 Ваш лот продан!",
        message="Лот продан за $100.00.",
        auction_id=1,
        auction_title="Картина «Лотус»",
    )
    assert "💰 Ваш лот продан!" in out
    assert "$100.00" in out
    assert "Картина «Лотус»" in out


def test_none_auction_title_is_safe():
    """``auction_title=None`` is the no-lot-card branch — must not
    blow up on ``html.escape(None)``."""
    out = build_notification_email_html(
        notification_type_value="bid_placed",
        title="Hello",
        message="World",
        auction_id=None,
        auction_title=None,
    )
    assert "Hello" in out
    assert "World" in out
