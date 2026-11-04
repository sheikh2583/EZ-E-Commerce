from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.models import RateBucket


class Command(BaseCommand):
    help = "Delete expired hashed request-limit counters."

    def handle(self, *args, **options) -> None:
        deleted, _ = RateBucket.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f"Removed {deleted} expired rate buckets.")
