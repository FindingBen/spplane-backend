import json
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
                segment_list_id=automation_data.get('segment_list_id',None),
                period=automation_data.get('period',None),
                every=automation_data.get('every',None),
                sms_sender=automation_data['sms_sender'],
                user=user
            )

            return automation
        except Exception as e:
            raise ExceptionAutomationError(f"Failed to create automation: {str(e)}")
        
    @staticmethod
    def update_automation(automation_id, automation_data, user=None):

        try:
            automation = Automation.objects.get(id=automation_id, user=user)
        
            for key, value in automation_data.items():
                if hasattr(automation, key):
                    setattr(automation, key, value)
            
            automation.save()
            
            if automation.is_active is True and automation.status == 'activated' and automation.automation_type == 'recurring':
                
                AutomationService.create_periodic_task(sms_body=automation.sms_body,
                                                       sms_sender=automation.sms_sender,
                                                       segment_id=automation.segment_list_id,
                                                       user_id=user.id,
                                                       automation_id=automation.id)
            elif automation.status == 'deactivated' and automation.automation_type == 'recurring':
                task_id = automation.task_id
                AutomationService.remove_periodic_task(task_id)
            
            return automation
        except Automation.DoesNotExist:
            raise ValidationError("Automation not found or you don't have permission to update it.")
        except Exception as e:
            raise ExceptionAutomationError(f"Failed to update automation: {str(e)}")

    @staticmethod
    def get_automations_for_user(user):
        if user is None:
            raise ValidationError("User must be provided to retrieve automations.")
        return Automation.objects.filter(user=user)
    
    @staticmethod
    def create_periodic_task(sms_body:str,sms_sender:str, segment_id:str,user_id:str,automation_id:str) -> dict:
        from django_celery_beat.models import PeriodicTask, IntervalSchedule
        from django.utils.timezone import now
        from django.db import transaction
        from apps.automation.models import Automation

        # Map period strings to IntervalSchedule constants
        PERIOD_MAP = {
            'SECONDS': IntervalSchedule.SECONDS,
            'MINUTES': IntervalSchedule.MINUTES,
            'HOURS': IntervalSchedule.HOURS,
            'DAYS': IntervalSchedule.DAYS,
        }

        automation = Automation.objects.get(id=automation_id)
        period_value = PERIOD_MAP.get(automation.period)
        
        if period_value is None:
            raise ValueError(f"Invalid period: {automation.period}. Must be one of {list(PERIOD_MAP.keys())}")
        
        with transaction.atomic():
            schedule, _ = IntervalSchedule.objects.get_or_create(
                    every=automation.every,
                    period=period_value
            )

            task, created = PeriodicTask.objects.update_or_create(
                    name='Activate recourent sms sending',
                    defaults={
                        'interval': schedule,
                        'task': 'apps.sms.tasks.create_and_dispatch_sms',
                        'start_time': now(),
                        'enabled': True,
                        'kwargs': json.dumps({"sms_body": str(sms_body),"sms_sender":str(sms_sender),"segment_id":str(segment_id),"user_id":str(user_id)})
                    }
            )
           
            automation.task_id = task.id
            automation.save()


        return {
                "status":200,
                "message": "Task scheduled!"
        }
        
    @staticmethod
    def remove_periodic_task(task_id) -> dict:
        from django_celery_beat.models import PeriodicTask
        if task_id:
            PeriodicTask.objects.filter(id=task_id).delete()
        return {
            "status": 200,
            "message": "Task deleted!"
        }