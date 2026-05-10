from django.urls import path

from apps.shopify.apis.views import (
    ShopifyCustomerImportView,
    ShopifyCustomerListView,
	ShopifyProductCreateWebhookView,
	ShopifyProductDeleteWebhookView,
    ShopifyProductImportView,
    ShopifyProductListView,
	ShopifyProductUpdateWebhookView,
)


urlpatterns = [
	path("customers/", ShopifyCustomerListView.as_view()),
	path("customers/import/", ShopifyCustomerImportView.as_view()),
	path("products/", ShopifyProductListView.as_view()),
	path("products/import/", ShopifyProductImportView.as_view()),
	path("products/product_webhook", ShopifyProductCreateWebhookView.as_view()),
	path("products/delete_product_webhook", ShopifyProductDeleteWebhookView.as_view()),
	path("products/update_product_webhook", ShopifyProductUpdateWebhookView.as_view()),
]
