import uuid
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

# Create your models here.
class SmsPackage(models.Model):
    package_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant_profile = models.ForeignKey(
        "accounts.ShopifyProfile",on_delete=models.CASCADE, related_name="sms_packages")
    external_package_id = models.CharField(max_length=255, blank=True, db_index=True)
    shopify_product_id = models.CharField(max_length=255, blank=True, db_index=True)
    shopify_product_handle = models.CharField(max_length=255, blank=True, db_index=True)
    shopify_product_title = models.CharField(max_length=255, blank=True)
    name = models.CharField(max_length=255)
    sms_count = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=False)
    currency = models.CharField(max_length=10, default='USD')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.external_package_id and self.name:
            self.external_package_id = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.external_package_id or self.shopify_product_handle or self.name


class MerchantBillingState(models.Model):
    merchant_profile = models.OneToOneField(
        'accounts.ShopifyProfile',
        on_delete=models.CASCADE,
        related_name='billing_state',
    )
    plan_public_name = models.CharField(max_length=100, blank=True)
    partner_development = models.BooleanField(default=False)
    shopify_plus = models.BooleanField(default=False)
    is_billable = models.BooleanField(default=False)
    checked_at = models.DateTimeField(default=timezone.now)
    raw_shop_snapshot = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f'{self.merchant_profile.shop_domain} ({self.plan_public_name or "unknown"})'


class PaymentOrder(models.Model):
    class Provider(models.TextChoices):
        SHOPIFY = 'shopify', 'Shopify'

    class PurchaseKind(models.TextChoices):
        ONE_TIME = 'one_time', 'One Time'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        SETTLED = 'settled', 'Settled'
        DECLINED = 'declined', 'Declined'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='payment_orders',
    )
    package = models.ForeignKey(
        'payment.SmsPackage',
        on_delete=models.PROTECT,
        related_name='payment_orders',
    )
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.SHOPIFY,
    )
    purchase_kind = models.CharField(
        max_length=20,
        choices=PurchaseKind.choices,
        default=PurchaseKind.ONE_TIME,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    provider_charge_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    confirmation_url = models.URLField(max_length=1000, blank=True)
    return_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    price_snapshot = models.JSONField(default=dict, blank=True)
    credits_snapshot = models.JSONField(default=dict, blank=True)
    plan_snapshot = models.JSONField(default=dict, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class WebhookEvent(models.Model):
    topic = models.CharField(max_length=100)
    shop_domain = models.CharField(max_length=255)
    external_event_id = models.CharField(max_length=255, blank=True)
    payload_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['topic', 'shop_domain', 'external_event_id'],
                condition=~models.Q(external_event_id=''),
                name='payment_unique_webhook_external_event',
            ),
        ]
        indexes = [
            models.Index(fields=['topic', 'shop_domain']),
            models.Index(fields=['processed_at']),
        ]
    