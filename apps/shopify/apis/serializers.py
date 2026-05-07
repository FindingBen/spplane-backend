from rest_framework import serializers


class ShopifyCustomerListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, default="")
    cursor = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    first = serializers.IntegerField(required=False, min_value=1, max_value=250, default=50)
    reverse = serializers.BooleanField(required=False, default=False)
