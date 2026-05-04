from rest_framework import serializers


class ShopifyCustomerListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, default="")
    cursor = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    first = serializers.IntegerField(required=False, min_value=1, max_value=250, default=50)
    reverse = serializers.BooleanField(required=False, default=False)


class ShopifyCustomerImportItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    marketing_state = serializers.CharField(required=False, allow_blank=True, default="NONE")


class ShopifyCustomerImportSerializer(serializers.Serializer):
    customers = ShopifyCustomerImportItemSerializer(many=True)
    segment_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
    )
    contact_list = serializers.IntegerField(required=False, allow_null=True, default=None)
