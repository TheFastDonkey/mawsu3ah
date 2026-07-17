import qrcode
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django_otp.plugins.otp_totp.models import TOTPDevice

User = get_user_model()


class Command(BaseCommand):
    help = "Create a superuser with a TOTP device for admin 2FA."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        email = options["email"]
        username = options["username"]
        password = options["password"]

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_staff": True, "is_superuser": True},
        )
        user.set_password(password)
        user.save()

        device, _ = TOTPDevice.objects.get_or_create(
            user=user,
            name="Admin TOTP",
            defaults={"confirmed": True},
        )

        url = device.config_url
        self.stdout.write(self.style.SUCCESS(f"Admin user: {email}"))
        self.stdout.write(f"Config URL: {url}")

        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.make()
        qr.print_ascii(out=self.stdout)
