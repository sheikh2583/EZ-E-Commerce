from django.db import migrations, models


def waive_existing_zone_fees(apps, schema_editor):
    delivery_zones = apps.get_model("shop", "DeliveryZone").objects.using(schema_editor.connection.alias)
    delivery_zones.exclude(fee=0).update(fee=0)


class Migration(migrations.Migration):
    dependencies = [("shop", "0005_pap_payment_and_webhooks")]

    operations = [
        migrations.AlterField(
            model_name="deliveryzone",
            name="fee",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.RunPython(waive_existing_zone_fees, migrations.RunPython.noop),
    ]
