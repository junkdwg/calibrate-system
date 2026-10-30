from django import template

from ..utils import fmt_dec

register = template.Library()


@register.filter
def dec(value, min_dp=2):
    return fmt_dec(value, int(min_dp))
