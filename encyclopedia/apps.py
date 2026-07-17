from django.apps import AppConfig


class EncyclopediaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "encyclopedia"

    def ready(self):
        # Register project-level deployment checks.
        import mawsu3ah.checks  # noqa: F401
