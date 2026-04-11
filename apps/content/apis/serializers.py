from rest_framework import serializers
from apps.content.models import Template, Content


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ['id', 'name', 'description', 'category', 'structure', 'thumbnail_url', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_name(self, value):
        # Simple field validation
        if len(value) < 3:
            raise serializers.ValidationError("Name must be at least 3 characters")
        return value

class ContentSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    
    class Meta:
        model = Content
        fields = ['id', 'user', 'template', 'template_name', 'structure', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
