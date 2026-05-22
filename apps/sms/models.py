import uuid
from django.db import models


class Sms(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="sms_messages",
    )
    campaign = models.ForeignKey(
        "campaign.Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_messages",
    )
    contact_list = models.ForeignKey(
        "contacts.ContactList",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_messages",
    )

    tracking_id = models.CharField(max_length=32, unique=True)
    sender = models.CharField(max_length=20)
    body = models.TextField(max_length=1600)
    rendered_content_snapshot = models.JSONField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("processing", "Processing"),
            ("sent", "Sent"),
            ("partial", "Partial"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
    )

    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    provider = models.CharField(max_length=50, blank=True)
    provider_campaign_id = models.CharField(max_length=255, blank=True)

    has_cta_links = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SmsPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sms = models.OneToOneField(
        "sms.Sms",
        on_delete=models.CASCADE,
        related_name="page",
    )
    source_content = models.ForeignKey(
        "content.Content",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_pages",
    )

    public_slug = models.SlugField(max_length=64, unique=True)
    page_status = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("published", "Published"),
            ("archived", "Archived"),
        ],
        default="draft",
    )

    content_snapshot = models.JSONField()
    snapshot_version = models.PositiveIntegerField(default=1)

    requires_token = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SmsPageAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    page = models.ForeignKey(
        "sms.SmsPage",
        on_delete=models.CASCADE,
        related_name="actions",
    )

    action_key = models.CharField(max_length=100)
    label = models.CharField(max_length=120)

    action_type = models.CharField(
        max_length=30,
        choices=[
            ("url", "URL"),
            ("deep_link", "Deep Link"),
            ("phone", "Phone"),
            ("email", "Email"),
            ("download", "Download"),
            ("form_submit", "Form Submit"),
            ("video", "Video"),
            ("custom", "Custom"),
        ],
    )

    target_url = models.URLField(max_length=500, blank=True)
    target_value = models.CharField(max_length=255, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("page", "action_key")]

class SmsRecipient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sms = models.ForeignKey(
        "sms.Sms",
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_recipients",
    )

    phone = models.CharField(max_length=20)
    access_token = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
            ("undelivered", "Undelivered"),
            ("opted_out", "Opted Out"),
        ],
        default="pending",
    )

    provider_message_id = models.CharField(max_length=255, blank=True)
    provider_status = models.CharField(max_length=100, blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)

    delivered_at = models.DateTimeField(null=True, blank=True)
    page_opened_at = models.DateTimeField(null=True, blank=True)
    last_interaction_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SmsEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sms = models.ForeignKey(
        "sms.Sms",
        on_delete=models.CASCADE,
        related_name="events",
    )
    recipient = models.ForeignKey(
        "sms.SmsRecipient",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )
    page_action = models.ForeignKey(
        "sms.SmsPageAction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    event_type = models.CharField(
        max_length=30,
        choices=[
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("delivered", "Delivered"),
            ("failed", "Failed"),
            ("page_view", "Page View"),
            ("video_play", "Video Play"),
            ("video_complete", "Video Complete"),
            ("cta_click", "CTA Click"),
            ("form_submit", "Form Submit"),
            ("opt_out", "Opt Out"),
        ],
    )

    component_key = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

class SmsOptIn(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="sms_opt_ins",
    )
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.CASCADE,
        related_name="sms_opt_ins",
    )

    phone = models.CharField(max_length=20)
    source = models.CharField(max_length=50)  # e.g., "web_form", "sms_reply", "import"

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("contact", "phone")]

class QrCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="qr_codes",
    )
    contact_list = models.ForeignKey(
        "contacts.ContactList",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qr_codes",
    )
    qr_source_signup = models.CharField(max_length=50)

    code_data = models.CharField(max_length=255)
    qr_image_url = models.URLField(max_length=500)

    created_at = models.DateTimeField(auto_now_add=True)