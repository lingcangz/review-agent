"""Local SMTP delivery for magic links. SMTP debug logging is never enabled."""

import smtplib
from email.message import EmailMessage
from os import getenv
from urllib.parse import urlencode


class SmtpMailer:
    def send_login(self, email: str, token: str, organization_id: str) -> None:
        query = urlencode({"email": email, "token": token, "organization_id": organization_id})
        link = f"{getenv('APP_BASE_URL', 'http://localhost:3000')}/auth/verify?{query}"
        message = EmailMessage()
        message["From"] = getenv("SMTP_FROM", "Review Agent <noreply@localhost>")
        message["To"] = email
        message["Subject"] = "Review Agent 登录链接"
        message.set_content(
            f"请在 15 分钟内使用此登录链接：\n{link}\n\n若非本人操作，请忽略此邮件。"
        )
        with smtplib.SMTP(
            getenv("SMTP_HOST", "localhost"), int(getenv("SMTP_PORT", "2525")), timeout=10
        ) as smtp:
            smtp.send_message(message)
