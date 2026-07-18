from django.urls import path
from .views import (
    RegisterView, LoginView, VerifyEmailView, GetUserInfoView, WallerViewset,GetStatisticNumbersView,
    ShopifyOAuthInitView, ShopifyOAuthCallbackView, ShopifyAuthLookupView,
    ShopifyCompleteSetupView,
)
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("verify-email/<uuid:token>/", VerifyEmailView.as_view()),
    path("login/", LoginView.as_view()),
    path("token/refresh/", TokenRefreshView.as_view()),
    path("me/", GetUserInfoView.as_view()),
    path("me/statistic-numbers/", GetStatisticNumbersView.as_view()),
    path("wallet/", WallerViewset.as_view()),
    # Shopify OAuth
    path("shopify/oauth/", ShopifyOAuthInitView.as_view()),
    path("shopify/callback/", ShopifyOAuthCallbackView.as_view()),
    path("shopify/auth/", ShopifyAuthLookupView.as_view()),
    path("shopify/complete-setup/", ShopifyCompleteSetupView.as_view()),
]