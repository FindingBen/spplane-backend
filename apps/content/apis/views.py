from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.content.models import Template, Content
from django.core.exceptions import ValidationError
from apps.content.service import ContentService, TemplateService
from .serializers import TemplateSerializer, ContentSerializer


class TemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve predefined templates.
    Admin-only creation via Django admin interface.
    """
    queryset = Template.objects.filter(is_active=True)
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset


class ContentViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for content (landing pages).
    """
    serializer_class = ContentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ContentService().get_user_contents(self.request.user)

    def perform_create(self, serializer):
        """Call static service method"""
        try:
            # Call static method directly
            ContentService.create_content(
                user=self.request.user,
                template_id=serializer.validated_data['template'].id,
                structure=serializer.validated_data['structure']
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    
