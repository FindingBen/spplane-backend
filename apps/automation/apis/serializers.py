from apps.automation.models import Automation, AutomationExecution, AutomationResult
from rest_framework import serializers



class AutomationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Automation
        fields = ['id', 'name', 'description','automation_type', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class AutomationExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationExecution
        fields = ['id', 'automation', 'started_at', 'completed_at', 'status']
        read_only_fields = ['id', 'started_at', 'completed_at']

class AutomationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationResult
        fields = ['id', 'execution', 'step_name', 'success', 'details']
        read_only_fields = ['id']

