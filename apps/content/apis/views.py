import json

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.content.models import Template
from django.core.exceptions import ValidationError
from apps.content.service import ContentService
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
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return ContentService().get_user_contents(self.request.user)

    def _get_template_id(self, request, default=None):
        return request.data.get('template') or request.data.get('template_id') or default

    def _get_structure(self, request, default=None):
        structure = request.data.get('structure', default)
        if structure is None:
            raise ValidationError('Structure must be a JSON object')

        if isinstance(structure, str):
            structure = json.loads(structure)

        return structure

    def create(self, request):
        try:
            template_id = self._get_template_id(request)
            structure = self._get_structure(request)

            content = ContentService.create_content(
                user=request.user,
                template_id=template_id,
                structure=structure,
                files=request.FILES,
            )
            serializer = self.get_serializer(content)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except json.JSONDecodeError:
            return Response({'error': 'Structure must be valid JSON.'}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *_, **kwargs):
        content = self.get_object()
        partial = kwargs.get('partial', False)

        try:
            template_id = self._get_template_id(
                request,
                default=content.template_id if partial else None,
            )
            structure = self._get_structure(
                request,
                default=content.structure if partial else None,
            )

            content = ContentService.update_content(
                content=content,
                template_id=template_id,
                structure=structure,
                files=request.FILES,
            )
            serializer = self.get_serializer(content)
            return Response(serializer.data)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except json.JSONDecodeError:
            return Response({'error': 'Structure must be valid JSON.'}, status=status.HTTP_400_BAD_REQUEST)


class ContentUploadViewSet(viewsets.ViewSet):
    """
    Endpoint for uploading content structure (e.g. from builder).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=False, methods=['post'])
    def upload(self, request):
        """Upload content structure"""
        template_id = request.data.get('template') or request.data.get('template_id')
        structure = request.data.get('structure')

        try:
            if isinstance(structure, str):
                structure = json.loads(structure)

            content = ContentService.create_content(
                user=request.user,
                template_id=template_id,
                structure=structure,
                files=request.FILES,
            )
            serializer = ContentSerializer(content, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except json.JSONDecodeError:
            return Response({'error': 'Structure must be valid JSON.'}, status=status.HTTP_400_BAD_REQUEST)
