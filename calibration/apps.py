from django.apps import AppConfig


class CalibrationConfig(AppConfig):
    name = "calibration"
    verbose_name = "ระบบสอบเทียบเครื่องมือ"

    def ready(self):
        from . import signals
        signals.connect()
