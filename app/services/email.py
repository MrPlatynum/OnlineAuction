import html
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import (
    EMAIL_FROM,
    PUBLIC_BASE_URL,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USERNAME,
)

logger = logging.getLogger(__name__)


# Brand palette — kept aligned with static/css/common.css (--accent /
# --bg-1) so a recipient skimming the inbox sees the same colour cue
# they get on the site. Hex literals are inlined into the HTML template
# because most mail clients strip CSS variables.
BRAND_ACCENT = "#e8a020"
BRAND_BG = "#0a0a0a"
BRAND_SURFACE = "#111113"
BRAND_BORDER = "#27272a"
BRAND_TEXT = "#fafafa"
BRAND_MUTED = "#a1a1aa"


# Per-type presentation: human-readable Russian label + accent colour
# for the badge. The badge accent overlays the brand orange — keeping
# it semantic (red for "you lost", green for "you won") helps mail
# triage at a glance without abandoning the brand identity.
_TYPE_PRESENTATION = {
    "bid_outbid":      ("Вас перебили",       "#f59e0b"),
    "bid_placed":      ("Новая ставка",       BRAND_ACCENT),
    "auction_ending":  ("Аукцион скоро закончится", "#f59e0b"),
    "auction_won":     ("Вы выиграли лот",    "#22c55e"),
    "auction_lost":    ("Аукцион завершён",   "#ef4444"),
    "auction_sold":    ("Лот продан",         "#22c55e"),
    "new_lot":         ("Новый лот",          BRAND_ACCENT),
}


async def send_email_notification(to_email: str, subject: str, html_content: str) -> None:
    """Send one email synchronously over SMTP.

    Surfaces ``aiosmtplib`` exceptions to the caller — the outbox
    worker relies on that to decide between "mark sent" and "schedule
    retry". The previous swallow-and-log behaviour was right for
    fire-and-forget tasks (nobody could act on the failure anyway);
    now that the outbox owns retry, a silent send would be a bug.

    Uses ``aiosmtplib`` so the SMTP handshake, login, and send all
    happen on the asyncio event loop without blocking it.
    """
    msg = MIMEMultipart('alternative')
    msg['From'] = EMAIL_FROM
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))

    await aiosmtplib.send(
        msg,
        hostname=SMTP_SERVER,
        port=SMTP_PORT,
        start_tls=True,
        username=SMTP_USERNAME or None,
        password=SMTP_PASSWORD or None,
    )

    logger.info("Email sent to %s: %s", to_email, subject)


def build_notification_email_html(
    notification_type_value: str,
    title: str,
    message: str,
    auction_id: int = None,
    auction_title: str = None,
) -> str:
    # Escape every user-controllable field before it's spliced into the
    # HTML template. ``title`` / ``message`` / ``auction_title`` flow
    # from auction titles, usernames and bid notification copy — any of
    # which can contain ``<`` / ``>`` / ``"`` from the user. Without
    # escaping, a lot title like ``<img src=x onerror=...>`` would
    # render as live HTML in the recipient's mail client.
    title = html.escape(title or "")
    message = html.escape(message or "")
    auction_title = html.escape(auction_title) if auction_title else None
    # PUBLIC_BASE_URL is operator-set, but it's still env-supplied and
    # spliced unquoted into an href — escape defensively so a misconfig
    # like ``PUBLIC_BASE_URL='" onclick="..."'`` can't break out of the
    # attribute. Cheap insurance for a single concat.
    base_url = html.escape(PUBLIC_BASE_URL, quote=True)

    type_label, accent = _TYPE_PRESENTATION.get(
        notification_type_value,
        ("Уведомление", BRAND_ACCENT),
    )

    auction_link = ""
    if auction_id:
        auction_link = (
            f'<a href="{base_url}/auction.html?id={auction_id}" '
            f'class="button">Перейти к лоту →</a>'
        )

    return _render_email(
        accent_color=accent,
        type_label=type_label,
        title=title,
        message=message,
        body_card=(
            f'<div class="auction-card">'
            f'<div class="auction-label">Лот</div>'
            f'<div class="auction-name">{auction_title}</div>'
            f'</div>'
            if auction_title else ""
        ),
        cta=auction_link,
        base_url=base_url,
    )


def build_password_reset_email_html(username: str, reset_link: str) -> str:
    """Email body for the /password-reset/request flow. The CTA goes
    to ``${PUBLIC_BASE_URL}/password-reset.html?token=<jwt>`` so the
    landing page can POST the token + new password to
    /api/password-reset/confirm."""
    safe_username = html.escape(username or "")
    safe_link = html.escape(reset_link, quote=True)
    base_url = html.escape(PUBLIC_BASE_URL, quote=True)
    cta = f'<a href="{safe_link}" class="button">Сбросить пароль →</a>'
    return _render_email(
        accent_color=BRAND_ACCENT,
        type_label="Сброс пароля",
        title=f"Сброс пароля для {safe_username}",
        message=(
            f"Привет, {safe_username}. Кто-то запросил сброс пароля для "
            "этой учётной записи — надеемся, что это были вы. Ссылка "
            "действует 1 час. Если это были не вы, проигнорируйте письмо: "
            "пароль останется прежним, и старая ссылка перестанет работать "
            "после первого сброса."
        ),
        body_card="",
        cta=cta,
        base_url=base_url,
    )


def build_password_changed_email_html(username: str) -> str:
    """Notification body sent after a successful /password-reset/confirm.
    No CTA — just a "your password was changed" notice so the legitimate
    user notices if their account was reset without their knowledge."""
    safe_username = html.escape(username or "")
    base_url = html.escape(PUBLIC_BASE_URL, quote=True)
    cta = f'<a href="{base_url}/index.html" class="button">Войти в Лотус →</a>'
    return _render_email(
        accent_color="#22c55e",
        type_label="Пароль изменён",
        title=f"Пароль изменён, {safe_username}",
        message=(
            "Пароль для этой учётной записи только что был успешно "
            "сброшен. Если это были не вы — напишите нам немедленно: "
            "кто-то получил доступ к вашему email-ящику и сменил пароль, "
            "нужно отозвать сессии и проверить активность."
        ),
        body_card="",
        cta=cta,
        base_url=base_url,
    )


def build_verification_email_html(username: str, verify_link: str) -> str:
    """Email body for the post-register verification flow. The CTA goes
    to ``${PUBLIC_BASE_URL}/verify-email.html?token=<jwt>`` so the
    landing page can POST the token to /api/verify-email."""
    safe_username = html.escape(username or "")
    safe_link = html.escape(verify_link, quote=True)
    base_url = html.escape(PUBLIC_BASE_URL, quote=True)
    cta = f'<a href="{safe_link}" class="button">Подтвердить email →</a>'
    return _render_email(
        accent_color=BRAND_ACCENT,
        type_label="Подтверждение email",
        title=f"Здравствуйте, {safe_username}!",
        message=(
            "Чтобы делать ставки и выставлять лоты на Лотус, подтвердите "
            "этот email. Ссылка действует 24 часа — после истечения "
            "запросите новую в настройках профиля."
        ),
        body_card="",
        cta=cta,
        base_url=base_url,
    )


def _render_email(
    *,
    accent_color: str,
    type_label: str,
    title: str,
    message: str,
    body_card: str,
    cta: str,
    base_url: str,
) -> str:
    year = datetime.now().year
    # Mail clients vary wildly in how they handle modern CSS — Outlook
    # desktop still rejects flexbox, Gmail strips <style> in some quoted
    # threads. The template sticks to: block layout, inline-friendly
    # styles, hex colours (no CSS variables), simple gradients only in
    # decorative places. Keep one <style> block in <head> and inline
    # the colour-critical props on each element as a fallback.
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: {BRAND_BG};
            color: {BRAND_TEXT};
        }}
        .email-wrapper {{ background: {BRAND_BG}; padding: 32px 16px; }}
        .container {{
            max-width: 560px;
            margin: 0 auto;
            background: {BRAND_SURFACE};
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid {BRAND_BORDER};
        }}
        .brand {{
            padding: 28px 28px 16px;
            border-bottom: 1px solid {BRAND_BORDER};
        }}
        .brand-logo {{
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.3px;
            color: {BRAND_ACCENT};
            margin: 0;
        }}
        .content {{ padding: 28px; }}
        .type-badge {{
            display: inline-block;
            padding: 6px 12px;
            background: rgba(232, 160, 32, 0.08);
            border: 1px solid {accent_color};
            border-radius: 999px;
            color: {accent_color};
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.2px;
            margin-bottom: 18px;
        }}
        h1.email-title {{
            color: {BRAND_TEXT};
            font-size: 22px;
            font-weight: 700;
            line-height: 1.3;
            margin: 0 0 14px 0;
        }}
        .message {{
            color: {BRAND_MUTED};
            font-size: 15px;
            line-height: 1.55;
            margin: 0 0 22px 0;
        }}
        .auction-card {{
            background: {BRAND_BG};
            border: 1px solid {BRAND_BORDER};
            border-radius: 12px;
            padding: 16px 18px;
            margin: 0 0 22px 0;
        }}
        .auction-label {{
            color: {BRAND_MUTED};
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            margin-bottom: 6px;
        }}
        .auction-name {{
            color: {BRAND_ACCENT};
            font-size: 17px;
            font-weight: 700;
            margin: 0;
            line-height: 1.35;
        }}
        .button {{
            display: inline-block;
            background: {BRAND_ACCENT};
            color: {BRAND_BG};
            padding: 12px 22px;
            text-decoration: none;
            border-radius: 10px;
            font-weight: 700;
            font-size: 14px;
        }}
        .footer {{
            padding: 20px 28px 26px;
            border-top: 1px solid {BRAND_BORDER};
            background: {BRAND_BG};
        }}
        .footer-text {{
            color: {BRAND_MUTED};
            font-size: 12px;
            line-height: 1.55;
            margin: 0 0 6px 0;
        }}
        .footer-link {{
            color: {BRAND_ACCENT};
            text-decoration: none;
        }}
        .footer-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body style="margin:0;padding:0;background:{BRAND_BG};color:{BRAND_TEXT};">
    <div class="email-wrapper" style="background:{BRAND_BG};padding:32px 16px;">
        <div class="container" style="max-width:560px;margin:0 auto;background:{BRAND_SURFACE};border:1px solid {BRAND_BORDER};border-radius:16px;overflow:hidden;">
            <div class="brand" style="padding:28px 28px 16px;border-bottom:1px solid {BRAND_BORDER};">
                <p class="brand-logo" style="margin:0;color:{BRAND_ACCENT};font-size:22px;font-weight:800;letter-spacing:-0.3px;">Лотус</p>
            </div>

            <div class="content" style="padding:28px;">
                <span class="type-badge" style="display:inline-block;padding:6px 12px;background:rgba(232,160,32,0.08);border:1px solid {accent_color};border-radius:999px;color:{accent_color};font-size:12px;font-weight:700;letter-spacing:0.2px;margin-bottom:18px;">{type_label}</span>

                <h1 class="email-title" style="margin:0 0 14px 0;color:{BRAND_TEXT};font-size:22px;font-weight:700;line-height:1.3;">{title}</h1>

                <p class="message" style="margin:0 0 22px 0;color:{BRAND_MUTED};font-size:15px;line-height:1.55;">{message}</p>

                {body_card}

                {cta}
            </div>

            <div class="footer" style="padding:20px 28px 26px;border-top:1px solid {BRAND_BORDER};background:{BRAND_BG};">
                <p class="footer-text" style="margin:0 0 6px 0;color:{BRAND_MUTED};font-size:12px;line-height:1.55;">
                    Это письмо отправлено автоматически. Отвечать на него не нужно.
                </p>
                <p class="footer-text" style="margin:0 0 6px 0;color:{BRAND_MUTED};font-size:12px;line-height:1.55;">
                    Управлять уведомлениями: <a href="{base_url}/profile.html" class="footer-link" style="color:{BRAND_ACCENT};text-decoration:none;">в настройках профиля</a>.
                </p>
                <p class="footer-text" style="margin:10px 0 0 0;color:{BRAND_MUTED};font-size:11px;line-height:1.55;opacity:0.7;">
                    © {year} Лотус
                </p>
            </div>
        </div>
    </div>
</body>
</html>"""
