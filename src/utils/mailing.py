import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random
import string

from .config import EMAIL, EMAIL_PASSWORD, SMTP_SERVER, SMTP_PORT
from ..messaging import logs


def send_code(email: str) -> str | None:

    for _ in range(3):
        try:
            server, login_response = create_and_login_smtp_server()
            assert login_response == 235
            break
        except (smtplib.SMTPServerDisconnected, AssertionError, TimeoutError) as error:
            logs.warn(f'Failed to login to SMTP server: {error}')
            time.sleep(5)
    else:
        logs.warn('Failed to login to SMTP server after several attempts', notify=True)
        return None

    code = generate_code()

    msg = MIMEMultipart()
    msg['From'] = server.user
    msg['To'] = email
    msg['Subject'] = 'Приглашение в чат'
    text = f'Ваш пригласительный код: {code}'
    msg.attach(MIMEText(text, 'plain'))


    for _ in range(3):
        try:
            server.send_message(msg, to_addrs=[email])
            break
        except (smtplib.SMTPServerDisconnected, TimeoutError) as error:
            logs.warn(f'Failed to send email: {error}')
            time.sleep(5)
    else:
        logs.warn(f'Failed to send email after several attempts: {email}', notify=True)
        server.quit()
        return None

    server.quit()
    return code


def create_and_login_smtp_server():
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)

    server.starttls()
    server.ehlo()

    login_response, _ = server.login(EMAIL, EMAIL_PASSWORD)

    return server, login_response


def generate_code(k = 6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=k))
