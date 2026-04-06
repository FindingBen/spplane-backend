import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be provided")

        email = self.normalize_email(email)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("user_type", "regular")

        if not password:
            raise ValueError("Superuser must have a password")

        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    objects = UserManager()
    email = models.EmailField(unique=True)
    username = None

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USER_TYPE_CHOICES = [
        ("regular", "Regular"),
        ("shopify", "Shopify"),
    ]
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class AuthProvider(models.Model):
    PROVIDER_CHOICES = [
        ("email", "Email"),
        ("shopify", "Shopify"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_providers")

    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)

    provider_user_id = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("provider", "provider_user_id")


class ShopifyProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="shopify_profile")

    shop_domain = models.CharField(max_length=255, unique=True)

    access_token = models.CharField(max_length=500)

    shop_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)

    installed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.shop_domain
    
class EmailVerification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_tokens")

    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    is_used = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)