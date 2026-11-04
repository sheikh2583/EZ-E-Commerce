from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

ROLES = {
    "Catalogue": (
        "view_category", "add_category", "change_category",
        "view_product", "add_product", "change_product",
        "view_productimage", "add_productimage", "change_productimage", "delete_productimage",
    ),
    "Fulfillment": ("view_order", "change_order", "view_orderitem", "view_paymentattempt", "view_paymentevent"),
    "Store management": ("view_storesettings", "change_storesettings", "view_deliveryzone", "add_deliveryzone", "change_deliveryzone"),
}


class Command(BaseCommand):
    help = "Create the named store groups and grant their initial permissions."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for name, codes in ROLES.items():
            group, _ = Group.objects.get_or_create(name=name)
            permissions = Permission.objects.filter(content_type__app_label="shop", codename__in=codes)
            group.permissions.add(*permissions)
        self.stdout.write(self.style.SUCCESS("Store groups are available."))
