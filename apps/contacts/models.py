from django.db import models
from apps.accounts.models import User
from uuid import uuid4

class ContactList(models.Model):
    unique_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    users = models.ForeignKey(User, on_delete=models.CASCADE)
    segment_name = models.CharField(max_length=50)
    shopify_list = models.BooleanField(default=False)
    contact_lenght = models.IntegerField(null=True, blank=True)
    created_at = models.DateField(
        auto_now_add=True)
    

class Contact(models.Model):
    STATUS_CHOICES = [
        ('subscribed', 'Subscribed'),
        ('opted_out', 'Opted Out'),      # STOP keyword reply
        ('bounced', 'Bounced'),           # invalid/unreachable number
        ('blocked', 'Blocked'),           # carrier-blocked
    ]

    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('import', 'Import'),
        ('shopify', 'Shopify'),
        ('api', 'API'),
        ('keyword', 'Keyword Opt-In'),    # e.g. texted JOIN to your number
    ]

    unique_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    contact_list = models.ForeignKey(ContactList, on_delete=models.CASCADE, related_name='contacts')
    phone = models.CharField(max_length=20)              # E.164 format: +12025551234
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='subscribed')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    opted_out_at = models.DateTimeField(null=True, blank=True)   # compliance audit trail
    custom_attributes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('contact_list', 'phone')]
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['contact_list', 'status']),
            models.Index(fields=['contact_list', 'created_at']),
        ]