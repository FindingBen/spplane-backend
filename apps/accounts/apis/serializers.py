from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed
from apps.accounts.models import ShopifyProfile, User


def build_user_payload(user, *, shopify_profile=None):
    if shopify_profile is None:
        shopify_profile = ShopifyProfile.objects.filter(user=user).only(
            "shop_domain",
            "first_time_import_customers",
        ).first()

    return {
        "id": str(user.id),
        "email": user.email,
        "user_type": user.user_type,
        "shop_domain": shopify_profile.shop_domain if shopify_profile is not None else "",
        "first_time_import_customers": (
            shopify_profile.first_time_import_customers if shopify_profile is not None else False
        ),
    }



class RegisterSerializer(serializers.Serializer):
    USER_TYPE_CHOICES = ["regular", "shopify"]
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    user_type = user_type = serializers.ChoiceField(choices=USER_TYPE_CHOICES)
    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value
    
class CustomTokenSerializer(TokenObtainPairSerializer):
    username_field = "email"

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user

        if not user.is_active:
            raise AuthenticationFailed("Email not verified")
        
        data["user"] = build_user_payload(self.user)

        return data