from .permissions import TECHNICIAN, has_role


def roles(request):
    u = request.user
    return {"is_technician": u.is_authenticated and has_role(u, TECHNICIAN)}
