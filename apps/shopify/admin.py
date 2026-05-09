from django.contrib import admin
from .models import ShopifyCustomerLink, ShopifyProduct, ShopifyProductMedia, ShopifyProductVariant

admin.site.register(ShopifyCustomerLink)


@admin.register(ShopifyProduct)
class ShopifyProductAdmin(admin.ModelAdmin):
	list_display = (
		"title",
		"shopify_profile",
		"status",
		"variant_count",
		"media_count",
		"shopify_updated_at",
		"deleted_at",
	)
	list_filter = ("status", "is_gift_card", "shopify_profile")
	search_fields = ("title", "handle", "shopify_product_id")


@admin.register(ShopifyProductVariant)
class ShopifyProductVariantAdmin(admin.ModelAdmin):
	list_display = ("title", "product", "sku", "price_amount", "inventory_quantity", "deleted_at")
	list_filter = ("product__shopify_profile",)
	search_fields = ("title", "sku", "shopify_variant_id")


@admin.register(ShopifyProductMedia)
class ShopifyProductMediaAdmin(admin.ModelAdmin):
	list_display = ("shopify_media_id", "product", "media_type", "position", "deleted_at")
	list_filter = ("media_type", "product__shopify_profile")
	search_fields = ("shopify_media_id", "source_url")

# Register your models here.
