from django.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'
    verbose_name = 'Agent Krypto'

    def ready(self):
        from app.startup import on_startup
        on_startup()
