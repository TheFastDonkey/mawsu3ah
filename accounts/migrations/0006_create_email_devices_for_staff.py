from django.db import migrations


def create_email_devices_for_staff(apps, schema_editor):
    """Create a confirmed EmailDevice for every active staff/superuser."""
    User = apps.get_model("accounts", "User")
    EmailDevice = apps.get_model("otp_email", "EmailDevice")

    for user in User.objects.filter(is_active=True, is_staff=True):
        EmailDevice.objects.get_or_create(
            user=user,
            name="Email",
            defaults={
                "confirmed": True,
                "email": user.email,
            },
        )


def delete_created_email_devices(apps, schema_editor):
    """Remove the Email devices this migration created."""
    User = apps.get_model("accounts", "User")
    EmailDevice = apps.get_model("otp_email", "EmailDevice")

    EmailDevice.objects.filter(
        user__in=User.objects.filter(is_active=True, is_staff=True),
        name="Email",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_remove_profile_linkedin"),
        ("otp_email", "0006_add_timestamps"),
    ]

    operations = [
        migrations.RunPython(
            create_email_devices_for_staff,
            reverse_code=delete_created_email_devices,
        ),
    ]
