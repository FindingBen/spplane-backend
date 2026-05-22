from django.core.exceptions import ValidationError
from .exceptions import ErrorExceptionCreation
from django.db import transaction

from apps.contacts.models import ContactList, Contact, SegmentMembership


class ContactListService:
    @staticmethod
    def _refresh_contact_length(contact_list):
        contact_list.contact_lenght = contact_list.memberships.count()
        contact_list.save(update_fields=['contact_lenght'])

    @staticmethod
    def create_contact_list(contact_list_data, user=None):
        create_data = {}
        create_data['users'] = user

        if 'segment_name' in contact_list_data:
            create_data['segment_name'] = contact_list_data.get('segment_name')

        if 'shopify_list' in contact_list_data:
            create_data['shopify_list'] = contact_list_data.get('shopify_list')

        if 'contact_lenght' in contact_list_data:
            create_data['contact_lenght'] = contact_list_data.get('contact_lenght')

        contact_list = ContactList.objects.create(**create_data)

        return contact_list

    @staticmethod
    def get_contact_lists_for_user(user):
        return ContactList.objects.filter(users=user)

    @staticmethod
    def update_contact_list(contact_list, contact_list_data, user=None):
        if contact_list.users != user:
            raise ValidationError("You don't have permission to update this contact list.")

        if 'segment_name' in contact_list_data:
            contact_list.segment_name = contact_list_data.get('segment_name')
        if 'shopify_list' in contact_list_data:
            contact_list.shopify_list = contact_list_data.get('shopify_list')
        if 'contact_lenght' in contact_list_data:
            contact_list.contact_lenght = contact_list_data.get('contact_lenght')
        contact_list.save()
        return contact_list

    @staticmethod
    def delete_contact_list(contact_list, user=None):
        if contact_list.users != user:
            raise ValidationError("You don't have permission to delete this contact list.")

        contact_list.delete()

    @staticmethod
    def remove_contact_membership(contact_list, contact, user=None):
        if contact_list.users != user:
            raise ValidationError("You don't have permission to update this contact list.")

        if contact.users != user:
            raise ValidationError("You don't have permission to update this contact.")

        membership = SegmentMembership.objects.filter(
            contact_list=contact_list,
            contact=contact,
        ).first()

        if membership is None:
            raise ValidationError("Contact is not a member of this segment.")

        membership.delete()
        ContactListService._refresh_contact_length(contact_list)


class ContactService:
    @staticmethod
    def _get_target_segments(contact_data, user):
        segment_ids = contact_data.get('segment_ids') or []
        legacy_contact_list = contact_data.get('contact_list')

        if legacy_contact_list is not None:
            segment_ids = list(segment_ids) + [legacy_contact_list]

        if not segment_ids:
            return ContactList.objects.none()

        contact_lists = ContactList.objects.filter(users=user, id__in=segment_ids)
        if contact_lists.count() != len(set(segment_ids)):
            raise ValidationError("One or more segment ids are invalid for this user.")

        return contact_lists

    @staticmethod
    def _refresh_segment_lengths(contact_lists):
        for contact_list in contact_lists:
            contact_list.contact_lenght = contact_list.memberships.count()
            contact_list.save(update_fields=['contact_lenght'])

    @staticmethod
    @transaction.atomic
    def create_contact(contact_data, user=None):
        if user is None:
            raise ValidationError("Authenticated user is required to create a contact.")

        contact_lists = ContactService._get_target_segments(contact_data, user)

        create_data = {'users': user}

        if 'phone' in contact_data:
            create_data['phone'] = contact_data.get('phone')

        if 'first_name' in contact_data:
            create_data['first_name'] = contact_data.get('first_name')

        if 'last_name' in contact_data:
            create_data['last_name'] = contact_data.get('last_name')

        if 'status' in contact_data:
            create_data['status'] = contact_data.get('status')

        if 'source' in contact_data:
            create_data['source'] = contact_data.get('source')

        if 'opted_out_at' in contact_data:
            create_data['opted_out_at'] = contact_data.get('opted_out_at')

        if 'custom_attributes' in contact_data:
            create_data['custom_attributes'] = contact_data.get('custom_attributes')

        phone = create_data.get('phone')
        if not phone:
            raise ValidationError("Phone is required.")

        defaults = {key: value for key, value in create_data.items() if key not in {'users', 'phone'}}
        contact, created = Contact.objects.get_or_create(users=user, phone=phone, defaults=defaults)

        if not created:
            for field, value in defaults.items():
                setattr(contact, field, value)
            contact.save()

        for contact_list in contact_lists:
            SegmentMembership.objects.get_or_create(contact_list=contact_list, contact=contact)

        ContactService._refresh_segment_lengths(contact_lists)
        return contact
    
    @staticmethod
    def qr_contact_opin(contact_data, qr_id:str) -> Contact:
        from apps.accounts.models import User
        from apps.sms.models import QrCode
        qr = QrCode.objects.filter(id=qr_id).first()
        
        
        contact_data['source'] = 'qr_code'
        contact = Contact.objects.create(**contact_data, users=qr.user)
        if contact:
            return contact
        
        raise ErrorExceptionCreation


    @staticmethod
    def get_all_contacts(user=None):
        queryset = Contact.objects.all().prefetch_related('segment_memberships__contact_list')
        if user is not None:
            queryset = queryset.filter(users=user)
        return queryset

    @staticmethod
    @transaction.atomic
    def update_contact(contact, contact_data, user=None):
        if user is not None and contact.users != user:
            raise ValidationError("You don't have permission to update this contact.")

        contact_lists = ContactService._get_target_segments(contact_data, user) if user is not None else ContactList.objects.none()

        if 'phone' in contact_data:
            contact.phone = contact_data.get('phone')
        if 'first_name' in contact_data:
            contact.first_name = contact_data.get('first_name')
        if 'last_name' in contact_data:
            contact.last_name = contact_data.get('last_name')
        if 'status' in contact_data:
            contact.status = contact_data.get('status')
        if 'source' in contact_data:
            contact.source = contact_data.get('source')
        if 'opted_out_at' in contact_data:
            contact.opted_out_at = contact_data.get('opted_out_at')
        if 'custom_attributes' in contact_data:
            contact.custom_attributes = contact_data.get('custom_attributes')
        contact.save()

        if user is not None and ('segment_ids' in contact_data or 'contact_list' in contact_data):
            SegmentMembership.objects.filter(contact=contact).exclude(contact_list__in=contact_lists).delete()
            for contact_list in contact_lists:
                SegmentMembership.objects.get_or_create(contact_list=contact_list, contact=contact)
            ContactService._refresh_segment_lengths(ContactList.objects.filter(users=user, memberships__contact=contact).distinct())

        return contact

    @staticmethod
    def delete_contact(contact, user=None):
        if user is not None and contact.users != user:
            raise ValidationError("You don't have permission to delete this contact.")

        contact_lists = ContactList.objects.filter(memberships__contact=contact).distinct()
        contact.delete()
        ContactService._refresh_segment_lengths(contact_lists)
