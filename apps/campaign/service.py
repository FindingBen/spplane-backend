from django.core.exceptions import ValidationError
from apps.campaign.models import Campaign


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