from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny,IsAuthenticated
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.automation.service import AutomationService
from rest_framework.response import Response
from apps.automation.apis.serializers import AutomationSerializer, AutomationExecutionSerializer, AutomationResultSerializer





class AutomationViewSet(viewsets.ModelViewSet):
    serializer_class = AutomationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AutomationService.get_automations_for_user(self.request.user)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            automation = AutomationService.update_automation(
                automation_id=kwargs['pk'],
                automation_data=serializer.validated_data,
                user=request.user
            )
            return Response(self.get_serializer(automation).data, status=status.HTTP_200_OK)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as error:
            return Response({'error': str(error)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            automation = AutomationService.create_automation(serializer.validated_data, request.user)
            return Response(self.get_serializer(automation).data, status=status.HTTP_201_CREATED)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)
