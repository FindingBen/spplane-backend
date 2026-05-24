from django.urls import include, path
from .views import AutomationViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register(r'v1', AutomationViewSet, basename='automations')

urlpatterns = [
    path('', include(router.urls)),
]