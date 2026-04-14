from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from .serializers import CampaignSerializer
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from apps.campaign.service import CampaignService


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CampaignService.get_campaigns_for_user(self.request.user)

    def perform_create(self, serializer):
        try:
            campaign_data = serializer.validated_data
            campaign = CampaignService.create_campaign(campaign_data, self.request.user)
            serializer.instance = campaign
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def perform_update(self, serializer):
        try:
            campaign_data = serializer.validated_data
            campaign = CampaignService.update_campaign(serializer.instance, campaign_data, self.request.user)
            serializer.instance = campaign
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)

    def perform_destroy(self, instance):
        try:
            CampaignService.delete_campaign(instance, self.request.user)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)