from collections import Counter

from django.core.management.base import BaseCommand

from shop.notifications import claim, mark_expired_leases, process


class Command(BaseCommand):
    help = "Send a bounded batch of due order notifications."

    def handle(self, *args, **options) -> None:
        expired = mark_expired_leases()
        outcomes: Counter[str] = Counter()
        for _ in range(30):
            job = claim()
            if job is None:
                break
            outcomes[process(job)] += 1
        self.stdout.write(f"Notification outcomes {dict(outcomes)}. Expired leases marked unknown: {expired}.")
