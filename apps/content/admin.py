from django.contrib import admin
from .models import Content, Template


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'description', 'category', 'thumbnail_url')
        }),
        ('Template Structure', {
            'fields': ('structure',),
            'classes': ('wide',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    readonly_fields = ['created_at']


@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'template', 'created_at']
    list_filter = ['template', 'created_at']
    search_fields = ['user__email']
    readonly_fields = ['user', 'created_at', 'updated_at']


