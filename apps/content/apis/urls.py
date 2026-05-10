from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TemplateViewSet, ContentViewSet, ProductContentGenerationView

router = DefaultRouter()
router.register(r'templates', TemplateViewSet, basename='template')
router.register(r'v1', ContentViewSet, basename='content')

urlpatterns = [
    path('generate/v1', ProductContentGenerationView.as_view({'post': 'create'})),
    path('generate/v1/', ProductContentGenerationView.as_view({'post': 'create'})),
    path('', include(router.urls)),
]
