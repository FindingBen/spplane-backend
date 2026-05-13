from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_shopifyprofile_connect_products'),
        ('payment', '0002_smspackage_external_package_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='smspackage',
            name='merchant_profile',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='sms_packages',
                to='accounts.shopifyprofile',
            ),
        ),
    ]