from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, DeliveryZone, Product, StoreSettings

CATALOGUE = {
    "Home": ("Storage basket", "Ceramic vase", "Woven throw", "Table lamp", "Cushion cover"),
    "Kitchen": ("Stoneware mug", "Serving bowl", "Glass carafe", "Wooden spoon set", "Cotton apron"),
    "Desk": ("Notebook", "Desk tray", "Pen case", "Weekly planner", "Bookend set"),
    "Travel": ("Canvas tote", "Packing cube", "Travel pouch", "Water bottle", "Luggage tag"),
    "Bath": ("Hand towel", "Soap dish", "Wash bag", "Bath mat", "Towel set"),
    "Garden": ("Ceramic planter", "Watering can", "Garden gloves", "Plant stand", "Seed tray"),
}
FINISHES = ("Natural", "Slate", "Olive", "Sand")


class Command(BaseCommand):
    help = "Add 120 synthetic products and illustrative zones without replacing existing records."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--allow-hosted-demo", "--allow-hosted-sandbox", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        hosted_demo = options["allow_hosted_demo"] and (
            settings.PAYMENT_MODE == "sandbox"
            or (settings.PAYMENT_MODE == "disabled" and settings.DEMO_CATALOGUE)
        )
        if settings.PAYMENT_MODE == "live" or not (settings.DEBUG or hosted_demo):
            raise CommandError("Demo seeding requires local debug settings or an explicitly enabled hosted demo.")
        products: list[Product] = []
        for position, (name, items) in enumerate(CATALOGUE.items(), 1):
            category, _ = Category.objects.get_or_create(slug=slugify(name), defaults={"name": name, "position": position})
            for item_index, item in enumerate(items):
                for finish_index, finish in enumerate(FINISHES):
                    index = len(products) + 1
                    price = (650 + position * 200 + item_index * 180 + finish_index * 75) * 100
                    products.append(Product(
                        category=category, name=f"{item} · {finish}",
                        slug=slugify(f"demo {item} {finish}"), sku=f"DEMO-{index:03}",
                        description=f"{item} in {finish.lower()}. This item is part of the synthetic demo catalogue.",
                        regular_price=price, sale_price=price * 85 // 100 if index % 5 == 0 else None,
                        stock=0 if index % 13 == 0 else 3 if index % 11 == 0 else 20,
                        featured=finish_index == 0 and item_index == 0,
                    ))
        Product.objects.bulk_create(products, ignore_conflicts=True)
        DeliveryZone.objects.get_or_create(code="inside-dhaka", defaults={"name": "Inside Dhaka"})
        DeliveryZone.objects.get_or_create(code="outside-dhaka", defaults={"name": "Outside Dhaka"})
        StoreSettings.objects.get_or_create(pk=1, defaults={
            "banner_title": "Everyday essentials",
            "banner_body": "Explore considered finds for home, work and the road.",
        })
        count = Product.objects.filter(sku__in=[product.sku for product in products]).count()
        self.stdout.write(self.style.SUCCESS(f"Demo catalogue contains {count} fixture SKUs."))
