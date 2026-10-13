"""
Envío de correos de verificación por SMTP.

Funciona con cualquier proveedor (Gmail, Outlook, Zoho, etc.) — solo hay
que llenar las variables de config.py. Para Gmail específicamente NO uses
tu contraseña normal: hay que generar una "Contraseña de aplicación" en
https://myaccount.google.com/apppasswords (requiere verificación en dos
pasos activada en la cuenta).
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config


def enviar_correo_verificacion(destinatario, username, link_verificacion):
    asunto = "Verifica tu cuenta"
    cuerpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
        <h2>¡Hola, {username}!</h2>
        <p>Gracias por registrarte. Para activar tu cuenta, haz clic en el siguiente botón:</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{link_verificacion}"
               style="background:#2563EB; color:white; padding:12px 24px;
                      text-decoration:none; border-radius:8px; display:inline-block;">
                Verificar mi cuenta
            </a>
        </p>
        <p>O copia y pega este link en tu navegador:</p>
        <p style="word-break: break-all; color:#555;">{link_verificacion}</p>
        <p style="color:#888; font-size:12px;">Este link expira en 24 horas. Si no creaste esta cuenta, ignora este correo.</p>
    </div>
    """
    return _enviar(destinatario, asunto, cuerpo_html)


def _enviar(destinatario, asunto, cuerpo_html):
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print("[email] ADVERTENCIA: SMTP no configurado (config.py). No se envió el correo.")
        print(f"[email] (modo debug) Destinatario: {destinatario} | Asunto: {asunto}")
        return False

    mensaje = MIMEMultipart("alternative")
    mensaje["Subject"] = asunto
    mensaje["From"] = config.SMTP_FROM or config.SMTP_USER
    mensaje["To"] = destinatario
    mensaje.attach(MIMEText(cuerpo_html, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as servidor:
            servidor.starttls()
            servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
            servidor.sendmail(config.SMTP_USER, destinatario, mensaje.as_string())
        return True
    except Exception as e:
        print(f"[email] Error al enviar correo: {e}")
        return False
