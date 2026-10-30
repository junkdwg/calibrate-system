from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed

from .permissions import TECHNICIAN


def technician_limit_message():
    return (f"กลุ่ม {TECHNICIAN} (ผู้ลงข้อมูล) มีได้สูงสุด "
            f"{settings.MAX_DATA_ENTRY_USERS} คน")


def technician_slots_full(exclude_user_pk=None):
    qs = User.objects.filter(groups__name=TECHNICIAN)
    if exclude_user_pk:
        qs = qs.exclude(pk=exclude_user_pk)
    return qs.count() >= settings.MAX_DATA_ENTRY_USERS


def _guard(sender, instance, action, reverse, pk_set, **kwargs):
    """Safety net for every code path (admin, shell, scripts)."""
    if action != "pre_add" or not pk_set:
        return
    tech = Group.objects.filter(name=TECHNICIAN).first()
    if not tech:
        return
    if not reverse:  # user.groups.add(...): instance is a User, pk_set = group ids
        if tech.pk in pk_set and technician_slots_full(exclude_user_pk=instance.pk):
            raise ValidationError(technician_limit_message())
    elif instance.pk == tech.pk:  # group.user_set.add(...): pk_set = user ids
        existing = set(User.objects.filter(groups=tech).values_list("pk", flat=True))
        if len(existing | set(pk_set)) > settings.MAX_DATA_ENTRY_USERS:
            raise ValidationError(technician_limit_message())


def connect():
    m2m_changed.connect(_guard, sender=User.groups.through,
                        dispatch_uid="limit_technician_users")
