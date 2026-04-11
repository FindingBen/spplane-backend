from django.db import models
from apps.accounts.models import User


# Template model
class Template(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=50)
    structure = models.JSONField()  # Empty structure for blank
    thumbnail_url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

# Content model
class Content(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    template = models.ForeignKey(Template, on_delete=models.PROTECT)  # Always has a template
    structure = models.JSONField()  # Final customized version
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)