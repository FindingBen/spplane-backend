from apps.contacts.models import ContactList
from apps.sms.models import SmsPage,QrCode,Sms,SmsPageAction,SmsRecipient,SmsEvent
from rest_framework import serializers
from apps.sms.models import Sms


class SmsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sms
        fields = ['id', 'user', 'campaign', 'contact_list', 'tracking_id', 'sender', 'body', 'rendered_content_snapshot', 'status', 'scheduled_at', 'sent_at', 'provider', 'provider_campaign_id', 'has_cta_links', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'tracking_id', 'created_at', 'updated_at']


class SmsPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsPage
        fields = ['id', 'sms', 'source_content', 'public_slug', 'page_status', 'content_snapshot', 'snapshot_version', 'requires_token', 'published_at', 'expires_at', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class SmsPageActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsPageAction
        fields = ['id', 'page', 'action_key', 'label', 'action_type', 'target_url', 'target_value', 'position', 'metadata', 'created_at']
        read_only_fields = ['id', 'created_at']


class SmsRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsRecipient
        fields = ['id', 'sms', 'contact', 'phone', 'access_token', 'status', 'provider_message_id', 'provider_status', 'error_code', 'error_message', 'delivered_at', 'page_opened_at', 'last_interaction_at', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class SmsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsEvent
        fields = ['id', 'sms', 'recipient', 'page_action', 'event_type', 'component_key', 'metadata', 'occurred_at', 'created_at']
        read_only_fields = ['id', 'created_at']


class SmsPublicPageSerializer(serializers.ModelSerializer):
    actions = serializers.SerializerMethodField()

    class Meta:
        model = SmsPage
        fields = [
            'public_slug',
            'content_snapshot',
            'snapshot_version',
            'requires_token',
            'published_at',
            'expires_at',
            'actions',
        ]

    def get_actions(self, obj):
        # Return a curated list of actions for the public page consumer
        actions_qs = obj.actions.order_by('position').all()
        return [
            {
                'action_key': a.action_key,
                'label': a.label,
                'action_type': a.action_type,
                'target_url': a.target_url,
                'target_value': a.target_value,
                'position': a.position,
            }
            for a in actions_qs
        ]

class QRCodeSerializer(serializers.ModelSerializer):
    segment_id = serializers.PrimaryKeyRelatedField(
        source='contact_list',
        queryset=ContactList.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = QrCode
        fields = ['id', 'qr_source_signup', 'segment_id', 'code_data', 'qr_image_url', 'created_at']
        read_only_fields = ['id', 'code_data', 'qr_image_url', 'created_at']