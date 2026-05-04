from django.db import models


class ShopifyCustomerLink(models.Model):
    """
    Stores the Shopify-side identity for a customer and optionally links it
    to one local Contact record when the customer is imported into the app.
    """

    shopify_profile = models.ForeignKey(
        "accounts.ShopifyProfile",
        on_delete=models.CASCADE,
        related_name="customer_links",
    )
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopify_links",
    )

    # Shopify GraphQL customer GID, e.g. gid://shopify/Customer/1234567890
    shopify_customer_id = models.CharField(max_length=255)

    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email_snapshot = models.EmailField(blank=True)
    phone_snapshot = models.CharField(max_length=20, blank=True)
    marketing_state = models.CharField(max_length=32, blank=True)

    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shopify_profile", "shopify_customer_id"],
                name="unique_shopify_customer_per_shop",
            )
        ]
        indexes = [
            models.Index(fields=["shopify_profile", "shopify_customer_id"]),
            models.Index(fields=["contact"]),
            models.Index(fields=["email_snapshot"]),
            models.Index(fields=["phone_snapshot"]),
        ]

    def __str__(self):
        return f"{self.shopify_profile.shop_domain}:{self.shopify_customer_id}"
