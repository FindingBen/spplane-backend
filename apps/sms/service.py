import uuid
from apps.sms.models import SmsEvent
from apps.sms.models import SmsRecipient
from apps.sms.models import SmsPageAction
from apps.sms.models import SmsPage
from django.core.exceptions import ValidationError
from apps.sms.models import Sms


class SmsService:
    @staticmethod
    def _generate_tracking_id():
        while True:
            candidate = uuid.uuid4().hex[:12]
            if not Sms.objects.filter(tracking_id=candidate).exists():
                return candidate

    @staticmethod
    def create_sms(sms_data, user=None):
        create_data = {}
        create_data['user'] = user

        if 'campaign' in sms_data:
            create_data['campaign'] = sms_data.get('campaign')

        if 'contact_list' in sms_data:
            create_data['contact_list'] = sms_data.get('contact_list')

        create_data['tracking_id'] = SmsService._generate_tracking_id()

        if 'sender' in sms_data:
            create_data['sender'] = sms_data.get('sender')

        if 'body' in sms_data:
            create_data['body'] = sms_data.get('body')

        if 'rendered_content_snapshot' in sms_data:
            create_data['rendered_content_snapshot'] = sms_data.get('rendered_content_snapshot')

        if 'status' in sms_data:
            create_data['status'] = sms_data.get('status')

        if 'scheduled_at' in sms_data:
            create_data['scheduled_at'] = sms_data.get('scheduled_at')

        if 'sent_at' in sms_data:
            create_data['sent_at'] = sms_data.get('sent_at')

        if 'provider' in sms_data:
            create_data['provider'] = sms_data.get('provider')

        if 'provider_campaign_id' in sms_data:
            create_data['provider_campaign_id'] = sms_data.get('provider_campaign_id')

        if 'has_cta_links' in sms_data:
            create_data['has_cta_links'] = sms_data.get('has_cta_links')

        sms = Sms.objects.create(**create_data)

        return sms

    @staticmethod
    def get_smses_for_user(user):
        return Sms.objects.filter(user=user)

    @staticmethod
    def update_sms(sms, sms_data, user=None):
        if sms.user != user:
            raise ValidationError("You don't have permission to update this sms.")

        if 'campaign' in sms_data:
            sms.campaign = sms_data.get('campaign')
        if 'contact_list' in sms_data:
            sms.contact_list = sms_data.get('contact_list')
        if 'sender' in sms_data:
            sms.sender = sms_data.get('sender')
        if 'body' in sms_data:
            sms.body = sms_data.get('body')
        if 'rendered_content_snapshot' in sms_data:
            sms.rendered_content_snapshot = sms_data.get('rendered_content_snapshot')
        if 'status' in sms_data:
            sms.status = sms_data.get('status')
        if 'scheduled_at' in sms_data:
            sms.scheduled_at = sms_data.get('scheduled_at')
        if 'sent_at' in sms_data:
            sms.sent_at = sms_data.get('sent_at')
        if 'provider' in sms_data:
            sms.provider = sms_data.get('provider')
        if 'provider_campaign_id' in sms_data:
            sms.provider_campaign_id = sms_data.get('provider_campaign_id')
        if 'has_cta_links' in sms_data:
            sms.has_cta_links = sms_data.get('has_cta_links')
        sms.save()
        return sms

    @staticmethod
    def delete_sms(sms, user=None):
        if sms.user != user:
            raise ValidationError("You don't have permission to delete this sms.")

        sms.delete()


class SmsPageService:
    @staticmethod
    def create_sms_page(sms_page_data, user=None):
        create_data = {}

        if 'sms' in sms_page_data:
            create_data['sms'] = sms_page_data.get('sms')

        if 'source_content' in sms_page_data:
            create_data['source_content'] = sms_page_data.get('source_content')

        if 'public_slug' in sms_page_data:
            create_data['public_slug'] = sms_page_data.get('public_slug')

        if 'page_status' in sms_page_data:
            create_data['page_status'] = sms_page_data.get('page_status')

        if 'content_snapshot' in sms_page_data:
            create_data['content_snapshot'] = sms_page_data.get('content_snapshot')

        if 'snapshot_version' in sms_page_data:
            create_data['snapshot_version'] = sms_page_data.get('snapshot_version')

        if 'requires_token' in sms_page_data:
            create_data['requires_token'] = sms_page_data.get('requires_token')

        if 'published_at' in sms_page_data:
            create_data['published_at'] = sms_page_data.get('published_at')

        if 'expires_at' in sms_page_data:
            create_data['expires_at'] = sms_page_data.get('expires_at')

        sms_page = SmsPage.objects.create(**create_data)

        return sms_page

    @staticmethod
    def get_all_sms_pages():
        return SmsPage.objects.all()

    @staticmethod
    def update_sms_page(sms_page, sms_page_data, user=None):
        if 'sms' in sms_page_data:
            sms_page.sms = sms_page_data.get('sms')
        if 'source_content' in sms_page_data:
            sms_page.source_content = sms_page_data.get('source_content')
        if 'public_slug' in sms_page_data:
            sms_page.public_slug = sms_page_data.get('public_slug')
        if 'page_status' in sms_page_data:
            sms_page.page_status = sms_page_data.get('page_status')
        if 'content_snapshot' in sms_page_data:
            sms_page.content_snapshot = sms_page_data.get('content_snapshot')
        if 'snapshot_version' in sms_page_data:
            sms_page.snapshot_version = sms_page_data.get('snapshot_version')
        if 'requires_token' in sms_page_data:
            sms_page.requires_token = sms_page_data.get('requires_token')
        if 'published_at' in sms_page_data:
            sms_page.published_at = sms_page_data.get('published_at')
        if 'expires_at' in sms_page_data:
            sms_page.expires_at = sms_page_data.get('expires_at')
        sms_page.save()
        return sms_page

    @staticmethod
    def delete_sms_page(sms_page, user=None):
        sms_page.delete()


class SmsPageActionService:
    @staticmethod
    def create_sms_page_action(sms_page_action_data, user=None):
        create_data = {}

        if 'page' in sms_page_action_data:
            create_data['page'] = sms_page_action_data.get('page')

        if 'action_key' in sms_page_action_data:
            create_data['action_key'] = sms_page_action_data.get('action_key')

        if 'label' in sms_page_action_data:
            create_data['label'] = sms_page_action_data.get('label')

        if 'action_type' in sms_page_action_data:
            create_data['action_type'] = sms_page_action_data.get('action_type')

        if 'target_url' in sms_page_action_data:
            create_data['target_url'] = sms_page_action_data.get('target_url')

        if 'target_value' in sms_page_action_data:
            create_data['target_value'] = sms_page_action_data.get('target_value')

        if 'position' in sms_page_action_data:
            create_data['position'] = sms_page_action_data.get('position')

        if 'metadata' in sms_page_action_data:
            create_data['metadata'] = sms_page_action_data.get('metadata')

        sms_page_action = SmsPageAction.objects.create(**create_data)

        return sms_page_action

    @staticmethod
    def get_all_sms_page_actions():
        return SmsPageAction.objects.all()

    @staticmethod
    def update_sms_page_action(sms_page_action, sms_page_action_data, user=None):
        if 'page' in sms_page_action_data:
            sms_page_action.page = sms_page_action_data.get('page')
        if 'action_key' in sms_page_action_data:
            sms_page_action.action_key = sms_page_action_data.get('action_key')
        if 'label' in sms_page_action_data:
            sms_page_action.label = sms_page_action_data.get('label')
        if 'action_type' in sms_page_action_data:
            sms_page_action.action_type = sms_page_action_data.get('action_type')
        if 'target_url' in sms_page_action_data:
            sms_page_action.target_url = sms_page_action_data.get('target_url')
        if 'target_value' in sms_page_action_data:
            sms_page_action.target_value = sms_page_action_data.get('target_value')
        if 'position' in sms_page_action_data:
            sms_page_action.position = sms_page_action_data.get('position')
        if 'metadata' in sms_page_action_data:
            sms_page_action.metadata = sms_page_action_data.get('metadata')
        sms_page_action.save()
        return sms_page_action

    @staticmethod
    def delete_sms_page_action(sms_page_action, user=None):
        sms_page_action.delete()


class SmsRecipientService:
    @staticmethod
    def create_sms_recipient(sms_recipient_data, user=None):
        create_data = {}

        if 'sms' in sms_recipient_data:
            create_data['sms'] = sms_recipient_data.get('sms')

        if 'contact' in sms_recipient_data:
            create_data['contact'] = sms_recipient_data.get('contact')

        if 'phone' in sms_recipient_data:
            create_data['phone'] = sms_recipient_data.get('phone')

        if 'access_token' in sms_recipient_data:
            create_data['access_token'] = sms_recipient_data.get('access_token')

        if 'status' in sms_recipient_data:
            create_data['status'] = sms_recipient_data.get('status')

        if 'provider_message_id' in sms_recipient_data:
            create_data['provider_message_id'] = sms_recipient_data.get('provider_message_id')

        if 'provider_status' in sms_recipient_data:
            create_data['provider_status'] = sms_recipient_data.get('provider_status')

        if 'error_code' in sms_recipient_data:
            create_data['error_code'] = sms_recipient_data.get('error_code')

        if 'error_message' in sms_recipient_data:
            create_data['error_message'] = sms_recipient_data.get('error_message')

        if 'delivered_at' in sms_recipient_data:
            create_data['delivered_at'] = sms_recipient_data.get('delivered_at')

        if 'page_opened_at' in sms_recipient_data:
            create_data['page_opened_at'] = sms_recipient_data.get('page_opened_at')

        if 'last_interaction_at' in sms_recipient_data:
            create_data['last_interaction_at'] = sms_recipient_data.get('last_interaction_at')

        sms_recipient = SmsRecipient.objects.create(**create_data)

        return sms_recipient

    @staticmethod
    def get_all_sms_recipients():
        return SmsRecipient.objects.all()

    @staticmethod
    def update_sms_recipient(sms_recipient, sms_recipient_data, user=None):
        if 'sms' in sms_recipient_data:
            sms_recipient.sms = sms_recipient_data.get('sms')
        if 'contact' in sms_recipient_data:
            sms_recipient.contact = sms_recipient_data.get('contact')
        if 'phone' in sms_recipient_data:
            sms_recipient.phone = sms_recipient_data.get('phone')
        if 'access_token' in sms_recipient_data:
            sms_recipient.access_token = sms_recipient_data.get('access_token')
        if 'status' in sms_recipient_data:
            sms_recipient.status = sms_recipient_data.get('status')
        if 'provider_message_id' in sms_recipient_data:
            sms_recipient.provider_message_id = sms_recipient_data.get('provider_message_id')
        if 'provider_status' in sms_recipient_data:
            sms_recipient.provider_status = sms_recipient_data.get('provider_status')
        if 'error_code' in sms_recipient_data:
            sms_recipient.error_code = sms_recipient_data.get('error_code')
        if 'error_message' in sms_recipient_data:
            sms_recipient.error_message = sms_recipient_data.get('error_message')
        if 'delivered_at' in sms_recipient_data:
            sms_recipient.delivered_at = sms_recipient_data.get('delivered_at')
        if 'page_opened_at' in sms_recipient_data:
            sms_recipient.page_opened_at = sms_recipient_data.get('page_opened_at')
        if 'last_interaction_at' in sms_recipient_data:
            sms_recipient.last_interaction_at = sms_recipient_data.get('last_interaction_at')
        sms_recipient.save()
        return sms_recipient

    @staticmethod
    def delete_sms_recipient(sms_recipient, user=None):
        sms_recipient.delete()


class SmsEventService:
    @staticmethod
    def create_sms_event(sms_event_data, user=None):
        create_data = {}

        if 'sms' in sms_event_data:
            create_data['sms'] = sms_event_data.get('sms')

        if 'recipient' in sms_event_data:
            create_data['recipient'] = sms_event_data.get('recipient')

        if 'page_action' in sms_event_data:
            create_data['page_action'] = sms_event_data.get('page_action')

        if 'event_type' in sms_event_data:
            create_data['event_type'] = sms_event_data.get('event_type')

        if 'component_key' in sms_event_data:
            create_data['component_key'] = sms_event_data.get('component_key')

        if 'metadata' in sms_event_data:
            create_data['metadata'] = sms_event_data.get('metadata')

        if 'occurred_at' in sms_event_data:
            create_data['occurred_at'] = sms_event_data.get('occurred_at')

        sms_event = SmsEvent.objects.create(**create_data)

        return sms_event

    @staticmethod
    def get_all_sms_events():
        return SmsEvent.objects.all()

    @staticmethod
    def update_sms_event(sms_event, sms_event_data, user=None):
        if 'sms' in sms_event_data:
            sms_event.sms = sms_event_data.get('sms')
        if 'recipient' in sms_event_data:
            sms_event.recipient = sms_event_data.get('recipient')
        if 'page_action' in sms_event_data:
            sms_event.page_action = sms_event_data.get('page_action')
        if 'event_type' in sms_event_data:
            sms_event.event_type = sms_event_data.get('event_type')
        if 'component_key' in sms_event_data:
            sms_event.component_key = sms_event_data.get('component_key')
        if 'metadata' in sms_event_data:
            sms_event.metadata = sms_event_data.get('metadata')
        if 'occurred_at' in sms_event_data:
            sms_event.occurred_at = sms_event_data.get('occurred_at')
        sms_event.save()
        return sms_event

    @staticmethod
    def delete_sms_event(sms_event, user=None):
        sms_event.delete()