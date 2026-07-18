"""Create or update a permanent admin user from environment variables.

Required environment variables:
    ADMIN_EMAIL    - admin email address
    ADMIN_PASSWORD - admin password

Optional:
    ADMIN_USERNAME - defaults to the local part of ADMIN_EMAIL

The command also creates a confirmed EmailDevice so the admin can log in
via OTP email. Credentials are never stored in source code.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_email.models import EmailDevice

User = get_user_model()


class Command(BaseCommand):
    help = "Create or update a permanent admin user with email OTP (env vars only)."

    def handle(self, *args, **options):
        email = os.environ.get("ADMIN_EMAIL")
        password = os.environ.get("ADMIN_PASSWORD")
        username = os.environ.get("ADMIN_USERNAME")

        if not email or not password:
            raise CommandError(
                "Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables."
            )

        if username is None:
            username = email.split("@", 1)[0]

        user, created = User.objects.update_or_create(
            email=email,
            defaults={
                "username": username,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        user.set_password(password)
        user.save()

        device, device_created = EmailDevice.objects.get_or_create(
            user=user,
            name="Admin Email OTP",
            defaults={"confirmed": True, "email": email},
        )
        if not device.confirmed or device.email != email:
            device.confirmed = True
            device.email = email
            device.save()

        action = "created" if created else "updated"
        device_action = "created" if device_created else "updated"
        self.stdout.write(
            self.style.SUCCESS(f"Admin user {action}: {email} (username: {username})")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Email OTP device {device_action}: {device.name}")
        )
