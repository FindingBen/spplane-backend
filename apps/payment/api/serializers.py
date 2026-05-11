from rest_framework import serializers


class ShopifyOneTimeChargeSerializer(serializers.Serializer):
    package_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    currency_code = serializers.CharField(required=False, allow_blank=False, max_length=10, default='USD')
    test = serializers.BooleanField(required=False, default=False)
