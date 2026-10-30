from django.conf import settings

TECHNICIAN, REVIEWER, APPROVER = "Technician", "Reviewer", "Approver"
ROLES = [TECHNICIAN, REVIEWER, APPROVER]


def has_role(user, role):
    """Strictly by group membership - superusers get no implicit role,
    so the number of data-entry people really stays limited."""
    return user.is_authenticated and user.groups.filter(name=role).exists()


def can_edit(user, record):
    return (record.status == record.DRAFT
            and record.calibrator_id == user.id
            and has_role(user, TECHNICIAN))


def available_actions(user, record):
    """Workflow buttons this user may press right now."""
    seg = settings.ENFORCE_SEGREGATION
    acts = []
    if can_edit(user, record):
        acts.append("submit")
    if record.status == record.SUBMITTED and has_role(user, REVIEWER):
        if not (seg and record.calibrator_id == user.id):
            acts += ["review", "reject"]
    if record.status == record.REVIEWED and has_role(user, APPROVER):
        if not (seg and user.id in (record.calibrator_id, record.reviewer_id)):
            acts += ["approve", "reject"]
    return acts
