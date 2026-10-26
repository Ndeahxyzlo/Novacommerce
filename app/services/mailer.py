import smtplib
from email.message import EmailMessage

from flask import current_app


def mail_configured():
    return bool(current_app.config.get("MAIL_SERVER"))


def send_reset_email(user, url):
    if not mail_configured():
        if current_app.debug or current_app.testing:
            current_app.logger.warning("Enlace de recuperación para %s: %s", user.email, url)
        else:
            current_app.logger.error("MAIL_SERVER no está configurado; no se envió la recuperación a %s", user.email)
        return False

    message = EmailMessage()
    message["Subject"] = "Recuperación de contraseña - NovaCommerce"
    message["From"] = current_app.config["MAIL_SENDER"]
    message["To"] = user.email
    message.set_content(
        "Hola {},\n\nUsa este enlace para crear una nueva contraseña. Vence en una hora.\n\n{}\n\n"
        "Si no solicitaste el cambio, ignora este mensaje.\n".format(user.first_name, url)
    )
    try:
        with smtplib.SMTP(current_app.config["MAIL_SERVER"], current_app.config["MAIL_PORT"], timeout=15) as smtp:
            if current_app.config["MAIL_USE_TLS"]:
                smtp.starttls()
            if current_app.config["MAIL_USERNAME"]:
                smtp.login(current_app.config["MAIL_USERNAME"], current_app.config["MAIL_PASSWORD"])
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception("Falló el envío de correo de recuperación")
        return False
    return True
