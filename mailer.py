"""Envío de correos de PlanificA+ (SMTP). Opcional: si no hay Secrets de correo, la app sigue funcionando sin enviar.

Secrets (Streamlit):
  SMTP_USER     = "tu.cuenta@gmail.com"
  SMTP_PASSWORD = "contraseña de aplicación de 16 letras"  (Google → Seguridad → Contraseñas de aplicaciones)
  SMTP_HOST     = "smtp.gmail.com"   (opcional)
  SMTP_PORT     = 465                (opcional, SSL)
  APP_URL       = "https://planificaplus.streamlit.app"  (opcional)
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


def _get(secrets, k, d=""):
    try:
        return str(secrets[k]).strip()
    except Exception:
        return d


def configured(secrets) -> bool:
    return bool(_get(secrets, "SMTP_USER") and _get(secrets, "SMTP_PASSWORD"))


def send(secrets, to: str, subject: str, body: str) -> tuple[bool, str]:
    if not configured(secrets):
        return False, "El envío de correos no está configurado (faltan SMTP_USER y SMTP_PASSWORD en Secrets)."
    user = _get(secrets, "SMTP_USER")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = f"PlanificA+ <{user}>", to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(_get(secrets, "SMTP_HOST", "smtp.gmail.com"), int(_get(secrets, "SMTP_PORT", "465")),
                              context=ssl.create_default_context(), timeout=20) as srv:
            srv.login(user, _get(secrets, "SMTP_PASSWORD"))
            srv.send_message(msg)
        return True, f"Correo enviado a {to}."
    except smtplib.SMTPAuthenticationError:
        return False, "El servidor de correo rechazó el usuario o la contraseña de aplicación (revisa SMTP_USER / SMTP_PASSWORD)."
    except Exception as e:  # red, puerto, destinatario inválido…
        return False, f"No se pudo enviar el correo ({type(e).__name__})."


def welcome_text(name: str, username: str, temp_pw: str, url: str, owner_note: str, reactivated: bool = False) -> tuple[str, str]:
    subject = "PlanificA+ · Tu cuenta fue reactivada" if reactivated else "PlanificA+ · Tu cuenta de acceso"
    body = f"""Hola {name}:

{"Tu cuenta en PlanificA+ fue reactivada." if reactivated else "Se creó tu cuenta en PlanificA+ (control de obra)."}

  Ingreso:            {url}
  Usuario:            {username}
  Contraseña temporal: {temp_pw}

Al entrar por primera vez la app te pedirá crear una contraseña propia.
Importante: tienes 5 días para entrar; si no, la cuenta se desactiva y deberás pedir que la reactiven.

{owner_note}
Este es un correo automático, no lo respondas.
"""
    return subject, body
