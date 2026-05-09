from django.urls import path

from apps.shopify.apis.views import (
    ShopifyCustomerImportView,
    ShopifyCustomerListView,
    ShopifyProductImportView,
    ShopifyProductListView,
)


urlpatterns = [
	path("customers/", ShopifyCustomerListView.as_view()),
	path("customers/import/", ShopifyCustomerImportView.as_view()),
	path("products/", ShopifyProductListView.as_view()),
	path("products/import/", ShopifyProductImportView.as_view()),
]
