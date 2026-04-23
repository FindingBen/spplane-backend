from django.contrib import admin
from .models import Sms, SmsPage, SmsPageAction, SmsRecipient, SmsEvent


class SmsPageInline(admin.StackedInline):
	model = SmsPage
	extra = 0
	can_delete = False


@admin.register(Sms)
class SmsAdmin(admin.ModelAdmin):
	list_display = [
		"id",
		"tracking_id",
		"user",
		"campaign",
		"sender",
		"status",
		"scheduled_at",
		"sent_at",
		"created_at",
	]
	list_filter = ["status", "provider", "created_at", "scheduled_at"]
	search_fields = ["tracking_id", "sender", "provider_batch_id", "user__email"]
	readonly_fields = ["id", "created_at", "updated_at"]
	inlines = [SmsPageInline]


class SmsPageActionInline(admin.TabularInline):
	model = SmsPageAction
	extra = 0


@admin.register(SmsPage)
class SmsPageAdmin(admin.ModelAdmin):
	list_display = [
		"id",
		"sms",
		"public_slug",
		"page_status",
		"requires_token",
		"published_at",
		"expires_at",
		"created_at",
	]
	list_filter = ["page_status", "requires_token", "created_at"]
	search_fields = ["public_slug", "sms__tracking_id"]
	readonly_fields = ["id", "created_at", "updated_at"]
	inlines = [SmsPageActionInline]


@admin.register(SmsPageAction)
class SmsPageActionAdmin(admin.ModelAdmin):
	list_display = [
		"id",
		"page",
		"action_key",
		"label",
		"action_type",
		"position",
		"created_at",
	]
	list_filter = ["action_type", "created_at"]
	search_fields = ["action_key", "label", "page__public_slug", "page__sms__tracking_id"]
	ordering = ["page", "position"]
	readonly_fields = ["id", "created_at"]


@admin.register(SmsRecipient)
class SmsRecipientAdmin(admin.ModelAdmin):
	list_display = [
		"id",
		"sms",
		"contact",
		"phone",
		"status",
		"provider_message_id",
		"delivered_at",
		"created_at",
	]
	list_filter = ["status", "created_at", "delivered_at"]
	search_fields = [
		"phone",
		"provider_message_id",
		"sms__tracking_id",
		"contact__first_name",
		"contact__last_name",
	]
	readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(SmsEvent)
class SmsEventAdmin(admin.ModelAdmin):
	list_display = [
		"id",
		"sms",
		"recipient",
		"page_action",
		"event_type",
		"occurred_at",
		"created_at",
	]
	list_filter = ["event_type", "occurred_at", "created_at"]
	search_fields = [
		"sms__tracking_id",
		"recipient__phone",
		"component_key",
		"page_action__action_key",
	]
	readonly_fields = ["id", "created_at"]
