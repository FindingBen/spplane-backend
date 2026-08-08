from django.core.exceptions import ValidationError
from apps.campaign.models import Campaign
from apps.sms.models import Sms, SmsEvent, SmsPage, SmsPageAction, SmsRecipient


EVENT_TYPES = ['queued','sent','delivered','failed']

class CampaignService:
    @staticmethod
    def create_campaign(campaign_data, user):
        """
        Create a new campaign for the given user.
        :param campaign_data: dict containing campaign details (name, description, content_id)
        :param user: User instance who is creating the campaign
        :return: Campaign instance
        """
        content = campaign_data.get('content') or campaign_data.get('content_id')
        campaign = Campaign.objects.create(
            user=user,
            name=campaign_data.get('name'),
            description=campaign_data.get('description', ''),
            content=content,
        )
        return campaign
    
    @staticmethod
    def get_campaigns_for_user(user):
        """
        Retrieve all campaigns for a given user.
        :param user: User instance
        :return: QuerySet of Campaign instances
        """
        return Campaign.objects.filter(user=user)
        

    @staticmethod
    def update_campaign(campaign, campaign_data, user):
        """
        Update an existing campaign.
        :param campaign: Campaign instance to update
        :param campaign_data: dict containing updated campaign details
        :param user: User instance (for permission check)
        :return: Updated Campaign instance
        """
        if campaign.user != user:
            raise ValidationError("You don't have permission to update this campaign.")
        
        campaign.name = campaign_data.get('name', campaign.name)
        campaign.description = campaign_data.get('description', campaign.description)
        if 'content' in campaign_data:
            campaign.content = campaign_data.get('content')
        elif 'content_id' in campaign_data:
            campaign.content_id = campaign_data.get('content_id')
        campaign.status = campaign_data.get('status', campaign.status)
        campaign.save()
        return campaign

    @staticmethod
    def delete_campaign(campaign, user):
        """
        Delete a campaign.
        :param campaign: Campaign instance to delete
        :param user: User instance (for permission check)
        """
        if campaign.user != user:
            raise ValidationError("You don't have permission to delete this campaign.")
        
        campaign.delete()

    @staticmethod
    def get_campaign_analytics(user):
        """Gets analytic for specified campaign"""
        response = {}
        latest_campaign = Campaign.objects.filter(user=user, status='active').order_by('-created_at').first()
        if latest_campaign is None:
            response['error'] = 'No active campaign'
            return response

        sms_object = Sms.objects.filter(campaign=latest_campaign, status='sent').first()
        if sms_object is None:
            response['error'] = 'No Sms tied to this campaign'
            return response

        expected_delivery_volume = SmsRecipient.objects.filter(sms=sms_object).count()
        actual_delivery_volume = SmsRecipient.objects.filter(sms=sms_object, status='delivered').count()
        metrics = CampaignService.prepare_metrics(sms_object)
        response['name'] = latest_campaign.name or 'Default'
        response['metrics'] = metrics
        response['total_recipients'] = expected_delivery_volume
        response['delivered'] = actual_delivery_volume

        return response

    @staticmethod
    def prepare_metrics(sms_object) -> list:
        # action_type choices are lowercase on SmsPageAction ('click', 'custom')
        metric_type_list = [{'event_type':'cta_click','action_type':'click'},{'event_type':'page_view','action_type':'custom'},
                            {'event_type':'Video Plays','action_type':'video'}]
        metric_list = []
        sms_page = SmsPage.objects.filter(sms=sms_object).first()

        for metric in metric_type_list:
            metric_events = SmsEvent.objects.filter(sms=sms_object, event_type=metric['event_type'])
            page_action = None
            if sms_page is not None:
                page_action = SmsPageAction.objects.filter(page=sms_page, action_type=metric['action_type']).first()

            metric_object = {
                'label': page_action.label if page_action else metric['event_type'],
                'value': metric_events.count(),
            }
            metric_list.append(metric_object)

        return metric_list

