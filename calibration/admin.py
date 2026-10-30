from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .formdefs import FORMS
from .permissions import TECHNICIAN
from .signals import technician_limit_message, technician_slots_full
from .models import AuditLog, CalibrationRecord, CalibrationRow, Department, Equipment


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


def _set_form_action(code):
    def action(modeladmin, request, queryset):
        n = queryset.update(form_code=code)
        modeladmin.message_user(request, f"ตั้งฟอร์ม {code} ให้ {n} รายการแล้ว")
    action.short_description = f"ตั้งฟอร์มเป็น {code} {FORMS[code].title}"
    action.__name__ = "set_form_" + code.replace("-", "_")
    return action


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "brand_model", "department", "form_code", "interval_months",
                    "last_calibrated", "active")
    list_editable = ("form_code", "interval_months")            # change the form right in the list
    list_filter = ("form_code", "department", "active")
    search_fields = ("code", "name", "serial_no", "brand_model")
    list_per_page = 100
    actions = [_set_form_action(c) for c in FORMS]


class ReadOnlyAdmin(admin.ModelAdmin):
    """Records/logs are changed only through the app workflow, never via admin."""
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


class RowInline(admin.TabularInline):
    model = CalibrationRow
    extra = 0
    can_delete = False
    def has_add_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False


@admin.register(CalibrationRecord)
class RecordAdmin(ReadOnlyAdmin):
    list_display = ("title_text", "form_code", "cal_date", "status", "calibrator", "reviewer", "approver")
    list_filter = ("status",)
    inlines = [RowInline]


@admin.register(AuditLog)
class AuditAdmin(ReadOnlyAdmin):
    list_display = ("at", "user", "action", "record", "detail")
    list_filter = ("action",)


class LimitedUserChangeForm(UserChangeForm):
    """Show a friendly error when the data-entry (Technician) quota is full."""
    def clean(self):
        data = super().clean()
        groups = data.get("groups")
        if groups and any(g.name == TECHNICIAN for g in groups):
            if technician_slots_full(exclude_user_pk=self.instance.pk):
                raise ValidationError(technician_limit_message())
        return data


admin.site.unregister(User)


@admin.register(User)
class CalibUserAdmin(UserAdmin):
    form = LimitedUserChangeForm
