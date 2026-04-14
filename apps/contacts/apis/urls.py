from .views import ContactViewSet
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ContactListViewSet

router = DefaultRouter()
router.register(r'v1', ContactListViewSet, basename='contact_lists')

router.register(r'audience/v1', ContactViewSet, basename='contacts')

urlpatterns = [
    path('', include(router.urls)),
]
