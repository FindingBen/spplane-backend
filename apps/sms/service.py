import uuid
from io import BytesIO
import qrcode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from apps.sms.models import SmsEvent, SmsRecipient, SmsPageAction, SmsPage, Sms, QrCode
from apps.accounts.models import User

class SmsService:
    @staticmethod
    def _generate_tracking_id():
        while True:
            candidate = uuid.uuid4().hex[:12]
            if not Sms.objects.filter(tracking_id=candidate).exists():
                return candidate

    @staticmethod
    def validate_sms_data(sms_body:str, sms_sender:str, segment_id:str, status:None) -> dict:
        from apps.contacts.models import ContactList
        from apps.sms.excpections import ContactListNotFound


        contact_list = ContactList.objects.get(id=segment_id)
        if contact_list is None:
            raise ContactListNotFound("Segment list doesn't exist")
        
        sms_data = {
            "body":sms_body,
            "sender": sms_sender,
            "contact_list":contact_list,
            "status":status
        }

        return sms_data

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

        with transaction.atomic():
            sms = Sms.objects.create(**create_data)
            campaign = create_data.get('campaign')
            if campaign is not None:
                campaign_with_content = (
                    campaign.__class__.objects
                    .select_related('content')
                    .filter(id=campaign.id)
                    .first()
                )
                if campaign_with_content is not None and campaign_with_content.content is not None:
                    SmsPageService._create_page_with_actions(sms, campaign_with_content.content)

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
    ACTION_COMPONENT_TYPES = {
        'cta': 'url',
        'form': 'form_submit',
        'video': 'video',
    }

    @staticmethod
    def _generate_public_slug():
        while True:
            candidate = uuid.uuid4().hex[:16]
            if not SmsPage.objects.filter(public_slug=candidate).exists():
                return candidate

    @staticmethod
    def _create_page_with_actions(sms, content):
        page = SmsPage.objects.create(
            sms=sms,
            source_content=content,
            public_slug=SmsPageService._generate_public_slug(),
            content_snapshot=content.structure,
        )
        components = content.structure.get('components', [])
        actions = []
        for position, component in enumerate(components):
            comp_type = component.get('type')
            if comp_type not in SmsPageService.ACTION_COMPONENT_TYPES:
                continue
            props = component.get('props', {})
            actions.append(SmsPageAction(
                page=page,
                action_key=component.get('id') or f'{comp_type}_{position}',
                label=props.get('label', comp_type),
                action_type=SmsPageService.ACTION_COMPONENT_TYPES[comp_type],
                target_url=props.get('url', props.get('href', '')),
                target_value=props.get('value', ''),
                position=position,
            ))
        if actions:
            SmsPageAction.objects.bulk_create(actions)
        return page






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
    def update_or_create_page(block_type:str, token:str) -> dict:
        response = {}

        # maps the public page block that was interacted with to its SmsPageAction fields
        BLOCK_TYPE_ACTIONS = {
            'cta': {'action_type': 'click', 'action_key': 'Click', 'label': 'Click'},
            'video-hero': {'action_type': 'video', 'action_key': 'Video', 'label': 'Video'},
            'carousel': {'action_type': 'click', 'action_key': 'Carousel', 'label': 'Carousel view'},
        }

        event_data = BLOCK_TYPE_ACTIONS.get(block_type)
        if event_data is None:
            response['status'] = 'Error'
            response['code'] = 400
            response['message'] = f"Unknown block_type '{block_type}'"
            return response

        recipient = SmsRecipient.objects.filter(access_token=token).first()
        if recipient is None:
            response['status'] = 'Error'
            response['code'] = 404
            response['message'] = 'Recipient not found'
            return response

        sms_page = SmsPage.objects.filter(sms=recipient.sms).first()
        if sms_page is None:
            response['status'] = 'Error'
            response['code'] = 404
            response['message'] = 'Page not found for this recipient'
            return response

        sms_page_action, created = SmsPageAction.objects.update_or_create(
            page=sms_page,
            action_key=event_data['action_key'],
            defaults={
                'action_type': event_data['action_type'],
                'label': event_data['label'],
            },
        )

        response['status'] = 'Success'
        response['code'] = 200
        response['created'] = created
        response['page_action_id'] = sms_page_action.id
        return response

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
    def optout_sms_recipient(recipient_token) -> dict:

        from apps.sms.models import SmsRecipient

        sms_recipient = SmsRecipient.objects.get(access_token=recipient_token)
        sms_recipient.status='opted_out'
        sms_recipient.save()
        
        # Also update the contact status so they don't appear as subscribed
        if sms_recipient.contact:
            sms_recipient.contact.status = 'unsubscribed'
            sms_recipient.contact.save()

        return {
            "status":201,
            "message":"Recipient opted out!"
        }



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
    def update_or_create_sms_event(block_type:str, token:str, page_action_id: str) -> dict:
        response = {}

        # SmsEvent.event_type only allows a fixed set of choices, no 'video'/'carousel' values exist
        BLOCK_TYPE_EVENTS = {
            'cta': 'cta_click',
            'video-hero': 'video_play',
            'carousel': 'cta_click',
        }

        event_type = BLOCK_TYPE_EVENTS.get(block_type)
        if event_type is None:
            response['status'] = 'Error'
            response['code'] = 400
            response['message'] = f"Unknown block_type '{block_type}'"
            return response

        recipient = SmsRecipient.objects.filter(access_token=token).first()
        if recipient is None:
            response['status'] = 'Error'
            response['code'] = 404
            response['message'] = 'Recipient not found'
            return response

        sms_page_action = SmsPageAction.objects.filter(id=page_action_id).first()
        if sms_page_action is None:
            response['status'] = 'Error'
            response['code'] = 404
            response['message'] = 'Page action not found'
            return response

        sms_event = SmsEvent.objects.create(
            sms=recipient.sms,
            recipient=recipient,
            page_action=sms_page_action,
            event_type=event_type,
            occurred_at=timezone.now(),
        )

        response['status'] = 'Success'
        response['code'] = 200
        response['sms_event_id'] = sms_event.id
        return response

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

class SmsAnalyticService:
    @staticmethod
    def overall_analytics_calculation(user:User) -> dict:
        """Sms analytics overall"""
        response = {}
        sms_objects = Sms.objects.filter(user=user)
        sms_scheduled = Sms.objects.filter(user=user, status='scheduled').count()
        sms_failed = Sms.objects.filter(user=user, status='failed').count()
        sms_sent = Sms.objects.filter(user=user, status='sent')
        sms_delivered = 0

        clicks = 0
        video_plays = 0
        views = 0

        for sms_object in sms_objects:

            page_obj = SmsPage.objects.get(sms=sms_object)

            clicks += SmsPageAction.objects.filter(page=page_obj,action_type='click').count()
            video_plays += SmsPageAction.objects.filter(page=page_obj,action_type='video').count()
            views += SmsPageAction.objects.filter(page=page_obj,action_type='custom').count()
            sms_delivered += SmsRecipient.objects.filter(sms=sms_object,status='delivered').count()

        response['delivered'] = sms_delivered
        response['scheduled'] = sms_scheduled
        response['failed'] = sms_failed
        response['sent'] = sms_sent
        response['metrics']['clicks'] = clicks
        response['metrics']['video_plays'] = video_plays
        response['metrics']['views'] = views

        return response




class QrCodeService:
    @staticmethod
    def retrieve_or_generate_qr_code_for_user(user):
        qr_code = (
            QrCode.objects.filter(
                user=user,
                qr_source_signup='customers',
                contact_list__isnull=True,
            )
            .order_by('-created_at')
            .first()
        )
        if qr_code is None:
            raise ValidationError('No QR code exists for the customers list.')
        return qr_code

    @staticmethod
    def create_qr_code(qr_code_data, user=None) -> dict:
        if user is None:
            raise ValidationError('Authenticated user is required to create a QR code.')

        source = qr_code_data.get('qr_source_signup')
        if source not in {'customers', 'segment'}:
            raise ValidationError("qr_source_signup must be either 'customers' or 'segment'.")

        contact_list = None
        if source == 'segment':
            contact_list = qr_code_data.get('contact_list')
            if contact_list is None:
                raise ValidationError('contact_list is required for segment QR codes.')
            if contact_list.users != user:
                raise ValidationError("You don't have permission to use this segment.")
            if QrCode.objects.filter(
                user=user,
                qr_source_signup='segment',
                contact_list=contact_list,
            ).exists():
                raise ValidationError('A QR code already exists for this segment.')
        else:
            if qr_code_data.get('contact_list') is not None:
                raise ValidationError('contact_list can only be used for segment QR codes.')
            if QrCode.objects.filter(
                user=user,
                qr_source_signup='customers',
                contact_list__isnull=True,
            ).exists():
                raise ValidationError('A QR code already exists for the customers list.')

        qr_code = QrCode.objects.create(
            user=user,
            qr_source_signup=source,
            contact_list=contact_list,
            code_data='',
            qr_image_url='',
        )

        signup_url = f"{settings.FRONTEND_URL.rstrip('/')}/sms-optin?q={qr_code.id}"

        img = qrcode.make(signup_url)
        image_url = QrCodeService.save_qr_image(img, filename=f"qr/{qr_code.id}.png")

        qr_code.code_data = signup_url
        qr_code.qr_image_url = image_url
        qr_code.save(update_fields=['code_data', 'qr_image_url'])

        return qr_code

    @staticmethod
    def save_qr_image(img, filename):
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        file_url = default_storage.save(filename, ContentFile(buffer.getvalue()))
        return default_storage.url(file_url)

class WelcomeSmsService:
    @staticmethod
    def _generate_tracking_id():
        while True:
            candidate = uuid.uuid4().hex[:12]
            if not Sms.objects.filter(tracking_id=candidate).exists():
                return candidate

    @staticmethod
    def check_automation(user):
        automation = user.automation_set.filter(
                automation_type="welcome_user",
                is_active=True,
            ).first()
        if automation is None:
            raise ValidationError('No active welcome automation found for user.')
        
        return automation

    @staticmethod
    def send_welcome_sms(customer_id:str, user) -> dict:
        from apps.sms.tasks import dispatch_single_sms
        has_active_automation = WelcomeSmsService.check_automation(user)

        if has_active_automation is not None:
            sms_data = {
                'user':user,
                'body':has_active_automation.sms_body,
                'sender':has_active_automation.sms_sender,
                'status':'scheduled',
                'provider':'vonage'
            }
            sms = SmsService.create_sms(sms_data)
            dispatch_single_sms.delay(sms.id, customer_id)

            return {
                "status": 200,
                "message": "Sms dispatched"
            }
        
class WeeklyOfferSmsService:
    pass
        
    
        
        
