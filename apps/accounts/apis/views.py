# pylint: disable=no-member
import logging

from django.conf import settings
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from .serializers import RegisterSerializer, CustomTokenSerializer
from apps.accounts.models import EmailVerification
from apps.accounts.service import AccountService, EmailVerificationService
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

logger = logging.getLogger(__name__)


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            user = AccountService.register_user(**serializer.validated_data)

            refresh = RefreshToken.for_user(user)

            return Response({
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "user_type": user.user_type
                },
                # "access": str(refresh.access_token),
                # "refresh": str(refresh)
            }, status=201)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class VerifyEmailView(APIView):
    def get(self, request, token):
        try:
            verification = EmailVerificationService.verify_email(token)
            return Response({"message": "Email verified successfully"}, status=200)
        except EmailVerification.DoesNotExist:
            return Response({"error": "Invalid token"}, status=400)


class GetUserInfoView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        return Response({
            "id": str(user.id),
            "email": user.email,
            "user_type": user.user_type
        }, status=200)


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenSerializer

class WallerViewset(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        wallet = user.wallet
        return Response({
            "balance": wallet.balance,
            "reserved": wallet.reserved,
            "updated_at": wallet.updated_at
        }, status=200)


# ---------------------------------------------------------------------------
# Shopify OAuth views
# ---------------------------------------------------------------------------

class ShopifyOAuthInitView(APIView):
    """
    GET /accounts/shopify/oauth/?shop=example.myshopify.com

    Redirects the merchant to Shopify's OAuth consent screen.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.shopify_service import ShopifyOAuthService

        shop = request.GET.get("shop", "").strip()
        if not shop:
            return Response({"error": "Missing shop parameter."}, status=status.HTTP_400_BAD_REQUEST)

        auth_url = ShopifyOAuthService.build_auth_url(shop)
        return redirect(auth_url)


class ShopifyOAuthCallbackView(APIView):
    """
    GET /accounts/shopify/callback/?shop=...&code=...

    Called by Shopify after the merchant approves the app.
    Exchanges the code for a permanent access token, creates (or updates)
    the user account, registers webhooks, issues a JWT, and redirects to
    the frontend.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.shopify_service import ShopifyOAuthService, ShopifyAccountService, verify_shopify_hmac

        shop = request.GET.get("shop", "").strip()
        code = request.GET.get("code", "").strip()

        if not shop or not code:
            return Response(
                {"error": "Missing shop or code parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not verify_shopify_hmac(request.GET.dict()):
            logger.warning("ShopifyOAuthCallback: invalid HMAC for shop %s", shop)
            return Response({"error": "Invalid HMAC signature."}, status=status.HTTP_403_FORBIDDEN)

        try:
            access_token = ShopifyOAuthService.exchange_code_for_token(shop, code)
            shop_data = ShopifyOAuthService.get_shop_info(shop, access_token)
        except ValueError as exc:
            logger.error("ShopifyOAuthCallback: OAuth failed for %s: %s", shop, exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user, created = ShopifyAccountService.get_or_create_user(shop, access_token, shop_data)

        if created:
            webhook_results = ShopifyAccountService.register_webhooks(shop, access_token)
            failed = [r for r in webhook_results if not r["success"]]
            if failed:
                logger.warning(
                    "ShopifyOAuthCallback: %d webhook(s) failed to register for %s: %s",
                    len(failed), shop, failed,
                )

        frontend_url = settings.FRONTEND_URL.rstrip("/")

        # New install or user has no password set → send to set-password page
        if created or not user.has_usable_password():
            from apps.accounts.shopify_service import generate_setup_token
            setup_token = generate_setup_token(shop, user.email)
            redirect_url = (
                f"{frontend_url}/set-password"
                f"?setup_token={setup_token}"
                f"&email={user.email}"
                f"&shop={shop}"
            )
        else:
            # Returning user with password → issue JWT and go to dashboard
            refresh = RefreshToken.for_user(user)
            redirect_url = (
                f"{frontend_url}/dashboard"
                f"?shop={shop}"
                f"&token={str(refresh.access_token)}"
                f"&refresh={str(refresh)}"
            )

        return redirect(redirect_url)


class ShopifyAuthLookupView(APIView):
    """
    GET /accounts/shopify/auth/?shop=example.myshopify.com

    Returns the JWT for a shop that has already installed the app.
    Used by the Shopify embedded app on reload when the session has expired.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.models import ShopifyProfile

        shop = request.GET.get("shop", "").strip()
        if not shop:
            return Response({"error": "Missing shop parameter."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            profile = ShopifyProfile.objects.select_related("user").get(shop_domain=shop)
        except ShopifyProfile.DoesNotExist:
            return Response({"error": "Shop not found."}, status=status.HTTP_404_NOT_FOUND)

        user = profile.user
        refresh = RefreshToken.for_user(user)

        return Response({
            "token": str(refresh.access_token),
            "refresh": str(refresh),
            "shop": shop,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "user_type": user.user_type,
            },
        }, status=status.HTTP_200_OK)


class ShopifyCompleteSetupView(APIView):
    """
    POST /accounts/shopify/complete-setup/

    Verifies the short-lived setup token issued after OAuth, sets the user's
    password, and returns a full JWT so the frontend can log them in.

    Body: { "setup_token": "...", "password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from django.core import signing
        from apps.accounts.shopify_service import verify_setup_token
        from apps.accounts.models import User

        setup_token = request.data.get("setup_token", "").strip()
        password = request.data.get("password", "").strip()

        if not setup_token or not password:
            return Response(
                {"error": "setup_token and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(password) < 8:
            return Response(
                {"error": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = verify_setup_token(setup_token)
        except signing.SignatureExpired:
            return Response(
                {"error": "Setup link has expired. Please reinstall the app."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"error": "Invalid setup token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=payload["email"])
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user.set_password(password)
        user.save(update_fields=["password"])

        refresh = RefreshToken.for_user(user)
        return Response({
            "token": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "user_type": user.user_type,
            },
        }, status=status.HTTP_200_OK)