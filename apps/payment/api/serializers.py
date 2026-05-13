from rest_framework import serializers

from apps.payment.models import SmsPackage


class SmsPackageListSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = SmsPackage
        fields = (
            'package_id',
            'external_package_id',
            'shopify_product_id',
            'shopify_product_handle',
            'shopify_product_title',
            'display_name',
            'name',
            'sms_count',
            'price',
            'currency',
            'is_active',
        )

    def get_display_name(self, obj):
        return obj.shopify_product_title or obj.name


class ShopifyOneTimeChargeSerializer(serializers.Serializer):
    package_id = serializers.CharField(max_length=255, trim_whitespace=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    currency_code = serializers.CharField(required=False, allow_blank=False, max_length=10, default='USD')
    test = serializers.BooleanField(required=False, default=False)

    def validate_package_id(self, value):
        normalized_value = (value or '').strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')
        return normalized_value
