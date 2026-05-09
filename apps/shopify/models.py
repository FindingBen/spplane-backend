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
    phone_snapshot = models.CharField(max_length=20, blank=True)
    marketing_state = models.CharField(max_length=32, blank=True)
    email_snapshot = models.EmailField(blank=True)
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
            models.Index(fields=["phone_snapshot"]),
        ]

    def __str__(self):
        return f"{self.shopify_profile.shop_domain}:{self.shopify_customer_id}"


class ShopifyProduct(models.Model):
    """
    Lean local projection of a merchant's Shopify product catalog.

    This stores only the fields needed to power product selection, block prefill,
    and checkout-link construction from landing pages.
    """

    shopify_profile = models.ForeignKey(
        "accounts.ShopifyProfile",
        on_delete=models.CASCADE,
        related_name="products",
    )

    shopify_product_id = models.CharField(max_length=255)

    title = models.CharField(max_length=255)
    handle = models.CharField(max_length=255, blank=True)
    description_html = models.TextField(blank=True)
    status = models.CharField(max_length=32, blank=True)
    tags = models.JSONField(default=list, blank=True)

    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)

    featured_image_url = models.URLField(max_length=2048, blank=True)
    total_inventory = models.IntegerField(null=True, blank=True)
    has_out_of_stock_variants = models.BooleanField(default=False)
    is_gift_card = models.BooleanField(default=False)
    variant_count = models.PositiveIntegerField(default=0)
    media_count = models.PositiveIntegerField(default=0)

    published_at = models.DateTimeField(null=True, blank=True)
    shopify_created_at = models.DateTimeField(null=True, blank=True)
    shopify_updated_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shopify_profile", "shopify_product_id"],
                name="unique_shopify_product_per_shop",
            )
        ]
        indexes = [
            models.Index(fields=["shopify_profile", "deleted_at"]),
            models.Index(fields=["shopify_profile", "shopify_updated_at"]),
            models.Index(fields=["shopify_profile", "handle"]),
        ]

    def __str__(self):
        return f"{self.shopify_profile.shop_domain}:{self.shopify_product_id}"


class ShopifyProductMedia(models.Model):
    """Normalized product media used to prefill image, carousel, and video blocks."""

    MEDIA_TYPE_CHOICES = [
        ("image", "Image"),
        ("video", "Video"),
        ("external_video", "External Video"),
        ("model_3d", "3D Model"),
        ("unknown", "Unknown"),
    ]

    product = models.ForeignKey(
        "shopify.ShopifyProduct",
        on_delete=models.CASCADE,
        related_name="media",
    )

    shopify_media_id = models.CharField(max_length=255)
    media_type = models.CharField(max_length=32, choices=MEDIA_TYPE_CHOICES, default="image")
    alt_text = models.CharField(max_length=255, blank=True)

    source_url = models.URLField(max_length=2048, blank=True)
    preview_image_url = models.URLField(max_length=2048, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    position = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "shopify_media_id"],
                name="unique_shopify_media_per_product",
            )
        ]
        indexes = [
            models.Index(fields=["product", "media_type"]),
            models.Index(fields=["product", "deleted_at"]),
        ]

    def __str__(self):
        return f"{self.product.shopify_product_id}:{self.shopify_media_id}"


class ShopifyProductVariant(models.Model):
    """Lean variant projection used for product selection and checkout links."""

    product = models.ForeignKey(
        "shopify.ShopifyProduct",
        on_delete=models.CASCADE,
        related_name="variants",
    )

    shopify_variant_id = models.CharField(max_length=255)

    title = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=255, blank=True)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    inventory_quantity = models.IntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)

    shopify_image_id = models.CharField(max_length=255, blank=True)
    featured_image_url = models.URLField(max_length=2048, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "shopify_variant_id"],
                name="unique_shopify_variant_per_product",
            )
        ]
        indexes = [
            models.Index(fields=["product", "deleted_at"]),
            models.Index(fields=["sku"]),
        ]

    def __str__(self):
        return f"{self.product.shopify_product_id}:{self.shopify_variant_id}"
