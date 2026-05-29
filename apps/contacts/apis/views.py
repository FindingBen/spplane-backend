from apps.contacts.service import ContactService
from .serializers import ContactSerializer
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from apps.contacts.service import ContactListService
from .serializers import ContactListSerializer



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

    @action(detail=True, methods=['delete'], url_path=r'members/(?P<contact_id>[^/.]+)')
    def remove_member(self, request, pk=None, contact_id=None):
        contact_list = self.get_object()
        contact = get_object_or_404(ContactService.get_all_contacts(request.user), pk=contact_id)

        try:
            ContactListService.remove_contact_membership(contact_list, contact, request.user)
        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ContactService.get_all_contacts(self.request.user)

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


class QRContactViewset(viewsets.ViewSet):

    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):

        try:
            pop_data = request.data
            qr_id = request.data.get('qr_id',None)
            if qr_id is None:
                return Response({'error': 'qr_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
            pop_data.pop('qr_id', None)  # Remove qr_id from data before validation
            serializer = ContactSerializer(data=pop_data)
            serializer.is_valid(raise_exception=True)
            contact = ContactService.qr_contact_optin(serializer.validated_data,qr_id)

            return Response("Contact created!", status=status.HTTP_201_CREATED)

        except ValidationError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = ContactSerializer(contact)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)