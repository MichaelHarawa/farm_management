from django.apps import AppConfig


class MobileSyncConfig(AppConfig):
    name = "apps.mobile_sync"

    def ready(self):
        from . import schema  # noqa: F401 — registers the JWT OpenAPI extension
        from . import reference_publication_signals  # noqa: F401 — gated before queries
