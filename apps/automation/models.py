from django.db import models



class Automation(models.Model):
    AUTOMTAION_TYPES =[
        ('welcome_user', 'Welcome sms'),
        ('weekly_offer', 'Weekly offer sms'),
    ]

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    automation_type = models.CharField(max_length=50, choices=AUTOMTAION_TYPES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AutomationExecution(models.Model):
    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name='executions')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='pending')

class AutomationResult(models.Model):
    execution = models.ForeignKey(AutomationExecution, on_delete=models.CASCADE, related_name='results')
    step_name = models.CharField(max_length=255)
    success = models.BooleanField(default=True)
    details = models.JSONField(null=True, blank=True)