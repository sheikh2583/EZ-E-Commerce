import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0004_ratebucket")]

    operations = [
        migrations.CreateModel(
            name="PapPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_id", models.UUIDField(null=True, unique=True)),
                ("payment_key", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("checkout_key", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("grant_id", models.UUIDField()),
                ("checkout_provider", models.CharField(max_length=12)),
                ("return_url", models.URLField(max_length=1000)),
                ("checkout_requested", models.BooleanField(default=False)),
                ("attempt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="pap_payment", to="shop.paymentattempt")),
            ],
        ),
        migrations.CreateModel(
            name="PapWebhookEvent",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("mode", models.CharField(max_length=12)),
                ("merchant_id", models.UUIDField()),
                ("payload", models.JSONField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("checked_at", models.DateTimeField(null=True)),
                ("processed_at", models.DateTimeField(null=True)),
            ],
            options={"indexes": [
                models.Index(fields=["mode", "merchant_id", "checked_at"],
                             condition=models.Q(processed_at__isnull=True), name="pap_webhook_pending"),
            ]},
        ),
    ]
