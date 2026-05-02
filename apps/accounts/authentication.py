import logging

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class ShopifyAuthentication(BaseAuthentication):
    """
    DRF authentication backend for requests coming from the Shopify embedded app.

    Reads the `Authorization: Shopify <access_token>` header, looks up the
    matching ShopifyProfile, and returns the associated User.

    Returning None (not raising) when the header is absent allows the
    standard JWTAuthentication to handle regular email-login requests.
    """

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Shopify "):
            return None  # not a Shopify request — let JWT authentication run

        token = auth_header[len("Shopify "):].strip()
        if not token:
            raise AuthenticationFailed("Empty Shopify access token.")

        from apps.accounts.models import ShopifyProfile

        try:
            profile = ShopifyProfile.objects.select_related("user").get(access_token=token)
        except ShopifyProfile.DoesNotExist:
            logger.warning("ShopifyAuthentication: no profile found for provided token.")
            return None  # unknown token — don't block, let other backends try

        user = profile.user
        if not user.is_active:
            raise AuthenticationFailed("Shopify user account is inactive.")

        return (user, token)

    def authenticate_header(self, request):
        return "Shopify"
