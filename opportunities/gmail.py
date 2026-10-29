"""Gmail SMTP backend with an explicit LOGIN challenge flow over verified TLS."""
import smtplib
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.smtp import EmailBackend


class LoginAuth:
    def login(self, user, password, *, initial_response_ok=True):
        self.ehlo_or_helo_if_needed()
        methods = self.esmtp_features.get('auth', '').upper().split()
        if 'LOGIN' not in methods:
            raise smtplib.SMTPNotSupportedError('Server does not advertise AUTH LOGIN')
        self.user, self.password = user, password
        return self.auth('LOGIN', self.auth_login, initial_response_ok=False)


class LoginSMTP(LoginAuth, smtplib.SMTP):
    pass


class LoginSMTPSSL(LoginAuth, smtplib.SMTP_SSL):
    pass


class GmailEmailBackend(EmailBackend):
    @property
    def connection_class(self):
        return LoginSMTPSSL if self.use_ssl else LoginSMTP

    def open(self):
        if self.host != 'smtp.gmail.com' or not (self.use_tls or self.use_ssl):
            raise ImproperlyConfigured('Gmail backend requires smtp.gmail.com and verified TLS/SSL')
        return super().open()
