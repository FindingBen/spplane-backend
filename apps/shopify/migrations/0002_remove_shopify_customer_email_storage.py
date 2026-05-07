from django.db import migrations


def remove_shopify_customer_emails(apps, _schema_editor):
    Contact = apps.get_model("contacts", "Contact")
    ShopifyCustomerLink = apps.get_model("shopify", "ShopifyCustomerLink")

    contacts_to_update = []
    for contact in Contact.objects.filter(source="shopify").iterator():
        custom_attributes = dict(contact.custom_attributes or {})
        if "email" not in custom_attributes:
            continue

        custom_attributes.pop("email", None)
        contact.custom_attributes = custom_attributes
        contacts_to_update.append(contact)

    if contacts_to_update:
        Contact.objects.bulk_update(contacts_to_update, ["custom_attributes"], batch_size=500)

    links_to_update = []
    for link in ShopifyCustomerLink.objects.iterator():
        raw_payload = dict(link.raw_payload or {})
        if "email" not in raw_payload:
            continue

        raw_payload.pop("email", None)
        link.raw_payload = raw_payload
        links_to_update.append(link)

    if links_to_update:
        ShopifyCustomerLink.objects.bulk_update(links_to_update, ["raw_payload"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("contacts", "0003_segmentmembership_and_more"),
        ("shopify", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(remove_shopify_customer_emails, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="shopifycustomerlink",
            name="email_snapshot",
        ),
    ]