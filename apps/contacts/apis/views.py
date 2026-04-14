from apps.contacts.service import ContactService
from .serializers import ContactSerializer
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.contacts.service import ContactListService
from .serializers import ContactListSerializer
from django.shortcuts import render



class ContactListViewSet(viewsets.ModelViewSet):
    serializer_class = ContactListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ContactListService.get_contact_lists_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            contact_list = ContactListService.create_contact_list(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(contact_list)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_contact_list = ContactListService.update_contact_list(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_contact_list)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            ContactListService.delete_contact_list(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ContactService.get_all_contacts()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            contact = ContactService.create_contact(serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = self.get_serializer(contact)
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_contact = ContactService.update_contact(instance, serializer.validated_data, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        output_serializer = self.get_serializer(updated_contact)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            ContactService.delete_contact(instance, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_403_FORBIDDEN)

        return Response(status=status.HTTP_204_NO_CONTENT)
