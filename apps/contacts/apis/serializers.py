from rest_framework import serializers
from apps.contacts.models import ContactList, Contact


class ContactListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactList
        fields = ['id', 'unique_id', 'users', 'segment_name', 'shopify_list', 'contact_lenght', 'created_at']
        read_only_fields = ['id', 'unique_id', 'users', 'created_at']


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ['id', 'unique_id', 'contact_list', 'phone', 'first_name', 'last_name', 'status', 'source', 'opted_out_at', 'custom_attributes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'unique_id', 'created_at', 'updated_at']
