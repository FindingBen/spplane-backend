from django.contrib import admin
from apps.payment.models import SmsPackage


@admin.register(SmsPackage)
class SmsPackageAdmin(admin.ModelAdmin):
	list_display = (
		'name',
		'external_package_id',
		'shopify_product_handle',
		'merchant_profile',
		'price',
		'sms_count',
		'is_active',
	)
	list_filter = ('is_active', 'currency')
	search_fields = (
		'name',
		'external_package_id',
		'shopify_product_handle',
		'shopify_product_id',
		'merchant_profile__shop_domain',
	)
