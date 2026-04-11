from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TemplateViewSet, ContentViewSet

router = DefaultRouter()
router.register(r'templates', TemplateViewSet, basename='template')
router.register(r'content', ContentViewSet, basename='content')

urlpatterns = [
    path('', include(router.urls)),
]
