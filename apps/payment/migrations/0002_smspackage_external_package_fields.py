from django.db import migrations, models
from django.utils.text import slugify


def populate_external_package_ids(apps, schema_editor):
    SmsPackage = apps.get_model('payment', 'SmsPackage')

    for package in SmsPackage.objects.filter(external_package_id=''):
        generated_identifier = slugify(package.name or '') or str(package.package_id)
        package.external_package_id = generated_identifier[:255]
        package.save(update_fields=['external_package_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='smspackage',
            name='external_package_id',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name='smspackage',
            name='shopify_product_handle',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name='smspackage',
            name='shopify_product_id',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name='smspackage',
            name='shopify_product_title',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(populate_external_package_ids, migrations.RunPython.noop),
    ]