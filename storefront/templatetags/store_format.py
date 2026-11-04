from django import template

register = template.Library()


@register.filter
def bdt(minor_units: int) -> str:
    taka, remainder = divmod(minor_units, 100)
    return f"৳{taka:,}.{remainder:02}" if remainder else f"৳{taka:,}"
