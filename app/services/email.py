import html
import logging
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


async def send_email_notification(to_email: str, subject: str, html_content: str):
    """Send an email notification.

    Uses ``aiosmtplib`` so the SMTP handshake, login, and send all
    happen on the asyncio event loop without blocking it. The previous
    ``smtplib`` implementation was a sync API that, called inside an
    ``async def``, blocked the entire FastAPI worker for the duration
    of the SMTP roundtrip — defeating the purpose of having an async
    framework in the first place.
    """
    try:
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
    except Exception:
        logger.exception("Failed to send email to %s", to_email)


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
    type_label = html.escape(notification_type_value.replace("_", " "))
    # PUBLIC_BASE_URL is operator-set, but it's still env-supplied and
    # spliced unquoted into an href — escape defensively so a misconfig
    # like ``PUBLIC_BASE_URL='" onclick="..."'`` can't break out of the
    # attribute. Cheap insurance for a single concat.
    base_url = html.escape(PUBLIC_BASE_URL, quote=True)

    auction_link = ""
    if auction_id:
        auction_link = (
            f'<a href="{base_url}/auction.html?id={auction_id}" '
            f'class="button">Перейти к аукциону →</a>'
        )

    icon_map = {
        'bid_outbid': ('😔', '#f59e0b'),
        'bid_placed': ('🎯', '#2dd4bf'),
        'auction_ending': ('⏰', '#f59e0b'),
        'auction_won': ('🎉', '#22c55e'),
        'auction_lost': ('😢', '#ef4444'),
        'auction_sold': ('💰', '#22c55e'),
    }
    icon, accent_color = icon_map.get(notification_type_value, ('🔔', '#2dd4bf'))

    return _render_email(
        accent_color=accent_color,
        icon=icon,
        type_label=type_label,
        title=title,
        message=message,
        body_card=(
            f'<div class="auction-card"><div class="auction-label">Лот</div>'
            f'<div class="auction-name">{auction_title}</div></div>'
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
        accent_color='#f59e0b',
        icon='🔑',
        type_label='password reset',
        title=f'Сброс пароля для {safe_username}',
        message=(
            'Кто-то — надеемся, что вы — запросил сброс пароля для этой '
            'учётной записи. Ссылка действует 1 час. Если это были '
            'не вы, проигнорируйте письмо: пароль останется прежним, '
            'и старая ссылка перестанет работать после первого сброса.'
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
    cta = (
        f'<a href="{base_url}/index.html" class="button">Войти в Лотус →</a>'
    )
    return _render_email(
        accent_color='#22c55e',
        icon='✅',
        type_label='password changed',
        title=f'Пароль изменён, {safe_username}',
        message=(
            'Пароль для этой учётной записи только что был успешно '
            'сброшен. Если это были не вы — напишите нам немедленно: '
            'кто-то получил доступ к вашему email-ящику и сменил '
            'пароль, нужно отозвать сессии и проверить активность.'
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
    cta = (
        f'<a href="{safe_link}" class="button">Подтвердить email →</a>'
    )
    return _render_email(
        accent_color='#2dd4bf',
        icon='✉️',
        type_label='email verification',
        title=f'Здравствуйте, {safe_username}!',
        message=(
            'Чтобы делать ставки и выставлять лоты на Лотус, подтвердите '
            'этот email. Ссылка действует 24 часа — после истечения '
            'запросите новую в настройках профиля.'
        ),
        body_card="",
        cta=cta,
        base_url=base_url,
    )


def _render_email(
    *,
    accent_color: str,
    icon: str,
    type_label: str,
    title: str,
    message: str,
    body_card: str,
    cta: str,
    base_url: str,
) -> str:
    return f"""
    <!DOCTYPE html>
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
                background: #0b0f14;
                color: #eaf2ff;
            }}
            .email-wrapper {{
                background: #0b0f14;
                padding: 40px 20px;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #0f1722;
                border-radius: 20px;
                overflow: hidden;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
                border: 1px solid #223147;
            }}
            .header {{
                background: linear-gradient(135deg, #2dd4bf, #a78bfa);
                padding: 40px 30px;
                text-align: center;
                position: relative;
            }}
            .header::before {{
                content: '';
                position: absolute;
                top: -50%;
                right: -20%;
                width: 400px;
                height: 400px;
                background: radial-gradient(circle, rgba(255,255,255,0.1), transparent);
                border-radius: 50%;
            }}
            .logo {{
                font-size: 32px;
                font-weight: 800;
                color: white;
                margin: 0 0 10px 0;
                position: relative;
                z-index: 1;
            }}
            .tagline {{
                color: rgba(255,255,255,0.9);
                font-size: 14px;
                margin: 0;
                position: relative;
                z-index: 1;
            }}
            .content {{
                padding: 40px 30px;
            }}
            .notification-badge {{
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 12px 20px;
                background: rgba(45, 212, 191, 0.1);
                border: 1px solid {accent_color};
                border-radius: 12px;
                margin-bottom: 24px;
            }}
            .notification-icon {{
                font-size: 32px;
            }}
            .notification-type {{
                color: {accent_color};
                font-weight: 700;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            h1 {{
                color: #eaf2ff;
                font-size: 28px;
                font-weight: 800;
                margin: 0 0 16px 0;
                line-height: 1.3;
            }}
            .message {{
                color: #9fb0c2;
                font-size: 16px;
                line-height: 1.6;
                margin: 0 0 24px 0;
            }}
            .auction-card {{
                background: #151f2e;
                border: 1px solid #223147;
                border-radius: 16px;
                padding: 20px;
                margin: 24px 0;
            }}
            .auction-label {{
                color: #9fb0c2;
                font-size: 12px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
            }}
            .auction-name {{
                color: #2dd4bf;
                font-size: 20px;
                font-weight: 800;
                margin: 0;
            }}
            .button {{
                display: inline-block;
                background: linear-gradient(135deg, #2dd4bf, #a78bfa);
                color: white;
                padding: 14px 28px;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 700;
                font-size: 16px;
                margin-top: 16px;
                transition: all 0.3s;
                box-shadow: 0 4px 15px rgba(45, 212, 191, 0.3);
            }}
            .button:hover {{
                box-shadow: 0 6px 20px rgba(45, 212, 191, 0.5);
                transform: translateY(-2px);
            }}
            .divider {{
                height: 1px;
                background: #223147;
                margin: 30px 0;
            }}
            .footer {{
                background: #0b0f14;
                padding: 30px;
                text-align: center;
            }}
            .footer-text {{
                color: #9fb0c2;
                font-size: 13px;
                line-height: 1.6;
                margin: 0 0 8px 0;
            }}
            .footer-link {{
                color: #2dd4bf;
                text-decoration: none;
            }}
            .footer-link:hover {{
                text-decoration: underline;
            }}
            .social-links {{
                margin-top: 20px;
            }}
            .social-links a {{
                display: inline-block;
                margin: 0 8px;
                font-size: 24px;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="email-wrapper">
            <div class="container">
                <div class="header">
                    <h1 class="logo">Лотус</h1>
                    <p class="tagline">Аукционы в реальном времени</p>
                </div>

                <div class="content">
                    <div class="notification-badge">
                        <span class="notification-icon">{icon}</span>
                        <span class="notification-type">{type_label}</span>
                    </div>

                    <h1>{title}</h1>

                    <p class="message">{message}</p>

                    {body_card}

                    {cta}

                    <div class="divider"></div>

                    <p class="message" style="font-size: 14px; margin: 0;">
                        💡 <strong>Совет:</strong> Включите уведомления на телефоне, чтобы не пропустить важные события!
                    </p>
                </div>

                <div class="footer">
                    <p class="footer-text">
                        Вы получили это письмо, потому что участвуете в аукционах на <strong>Лотус</strong>.
                    </p>
                    <p class="footer-text">
                        <a href="{base_url}/profile.html" class="footer-link">Изменить настройки уведомлений</a>
                    </p>
                    <p class="footer-text" style="font-size: 11px; color: #6b7280; margin-top: 20px;">
                        © 2025 Лотус. Все права защищены.<br>
                        Это автоматическое письмо, не отвечайте на него.
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
