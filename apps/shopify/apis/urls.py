from django.urls import path

from apps.shopify.apis.views import ShopifyCustomerImportView, ShopifyCustomerListView


urlpatterns = [
	path("customers/", ShopifyCustomerListView.as_view()),
	path("customers/import/", ShopifyCustomerImportView.as_view()),
]
