from rest_framework import serializers
from apps.contacts.models import ContactList, Contact


class ContactListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactList
        fields = ['id', 'unique_id', 'users', 'segment_name', 'shopify_list', 'contact_lenght', 'created_at']
        read_only_fields = ['id', 'unique_id', 'users', 'created_at']


class ContactSerializer(serializers.ModelSerializer):
    segment_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )
    contact_list = serializers.IntegerField(write_only=True, required=False)
    segments = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = ['id', 'unique_id', 'users', 'phone', 'first_name', 'last_name', 'status', 'source', 'opted_out_at', 'custom_attributes', 'segment_ids', 'contact_list', 'segments', 'created_at', 'updated_at']
        read_only_fields = ['id', 'unique_id', 'users', 'segments', 'created_at', 'updated_at']

    def get_segments(self, obj):
        return list(obj.segment_memberships.values_list('contact_list_id', flat=True))
