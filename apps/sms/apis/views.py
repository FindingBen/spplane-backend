from apps.sms.service import SmsEventService
from .serializers import SmsEventSerializer
from apps.sms.service import SmsRecipientService
from .serializers import SmsRecipientSerializer
from apps.sms.service import SmsPageActionService
from .serializers import SmsPageActionSerializer
from apps.sms.service import SmsPageService
from .serializers import SmsPageSerializer
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.sms.service import SmsService
from .serializers import SmsSerializer
from django.shortcuts import render

# Create your views here.


class SmsViewSet(viewsets.ModelViewSet):
    serializer_class = SmsSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsService.get_smses_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms = SmsService.create_sms(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms = SmsService.update_sms(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsService.delete_sms(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsPageViewSet(viewsets.ModelViewSet):
    serializer_class = SmsPageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsPageService.get_all_sms_pages()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_page = SmsPageService.create_sms_page(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_page)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_page = SmsPageService.update_sms_page(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_page)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsPageService.delete_sms_page(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsPageActionViewSet(viewsets.ModelViewSet):
    serializer_class = SmsPageActionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsPageActionService.get_all_sms_page_actions()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_page_action = SmsPageActionService.create_sms_page_action(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_page_action)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_page_action = SmsPageActionService.update_sms_page_action(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_page_action)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsPageActionService.delete_sms_page_action(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsRecipientViewSet(viewsets.ModelViewSet):
    serializer_class = SmsRecipientSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsRecipientService.get_all_sms_recipients()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_recipient = SmsRecipientService.create_sms_recipient(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_recipient)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_recipient = SmsRecipientService.update_sms_recipient(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_recipient)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsRecipientService.delete_sms_recipient(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SmsEventViewSet(viewsets.ModelViewSet):
    serializer_class = SmsEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SmsEventService.get_all_sms_events()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sms_event = SmsEventService.create_sms_event(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(sms_event)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_sms_event = SmsEventService.update_sms_event(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_sms_event)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            SmsEventService.delete_sms_event(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)
