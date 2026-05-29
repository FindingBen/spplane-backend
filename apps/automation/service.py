from apps.automation.models import Automation
from django.core.exceptions import ValidationError
from apps.automation.exceptions import ExceptionAutomationError




class AutomationService:

    @staticmethod
    def create_automation(automation_data, user=None):
        try:
            automation = Automation.objects.create(
                name=automation_data['name'],
                automation_type=automation_data['automation_type'],
                description=automation_data['description'],
                sms_body=automation_data['sms_body'],
                sms_sender=automation_data['sms_sender'],
                user=user
            )
            return automation
        except Exception as e:
            raise ExceptionAutomationError(f"Failed to create automation: {str(e)}")
        
    @staticmethod
    def get_automations_for_user(user):
        if user is None:
            raise ValidationError("User must be provided to retrieve automations.")
        return Automation.objects.filter(user=user)