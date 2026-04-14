from django.core.exceptions import ValidationError
from apps.contacts.models import ContactList, Contact


class ContactListService:
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


class ContactService:
    @staticmethod
    def create_contact(contact_data, user=None):
        create_data = {}

        if 'contact_list' in contact_data:
            create_data['contact_list'] = contact_data.get('contact_list')

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

        contact = Contact.objects.create(**create_data)

        return contact

    @staticmethod
    def get_all_contacts():
        return Contact.objects.all()

    @staticmethod
    def update_contact(contact, contact_data, user=None):
        if 'contact_list' in contact_data:
            contact.contact_list = contact_data.get('contact_list')
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
        return contact

    @staticmethod
    def delete_contact(contact, user=None):
        contact.delete()
