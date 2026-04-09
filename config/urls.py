from django.contrib import admin
from django.urls import path, include
from apps.accounts.apis.urls import urlpatterns as accounts_urls

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include(accounts_urls)),
]
