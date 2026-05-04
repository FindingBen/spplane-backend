import hashlib
import hmac
import logging

import requests
from django.conf import settings
from django.core import signing
from django.db import transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shopify setup token — short-lived signed token for the set-password flow.
# Uses Django's signing module (HMAC with SECRET_KEY, no DB needed).
# ---------------------------------------------------------------------------

SETUP_TOKEN_SALT = "shopify-setup-token"
SETUP_TOKEN_MAX_AGE = 600  # 10 minutes


def generate_setup_token(shop: str, email: str) -> str:
    """Returns a signed token encoding {shop, email}, valid for 10 minutes."""
    return signing.dumps({"shop": shop, "email": email}, salt=SETUP_TOKEN_SALT)


def verify_setup_token(token: str) -> dict:
    """
    Verifies and decodes a setup token.
    Returns {"shop": ..., "email": ...} on success.
    Raises signing.SignatureExpired or signing.BadSignature on failure.
    """
    return signing.loads(token, salt=SETUP_TOKEN_SALT, max_age=SETUP_TOKEN_MAX_AGE)


# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------

def verify_shopify_hmac(params: dict) -> bool:
    """
    Verifies the HMAC signature Shopify attaches to OAuth callback requests.

    Shopify includes an `hmac` query param computed over all other params
    sorted alphabetically and joined as key=value pairs. We recompute it
    with the API secret and compare using a constant-time comparison to
    prevent timing attacks.

    Pass request.GET.dict() — the function does NOT mutate the original dict.
    Returns True if the signature is valid, False otherwise.
    """
    params = dict(params)  # copy so we don't mutate the original
    received_hmac = params.pop("hmac", "")
    if not received_hmac:
        return False

    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    computed = hmac.new(
        settings.SHOPIFY_API_SECRET.encode("utf-8"),
        sorted_params.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, received_hmac)

# ---------------------------------------------------------------------------
# GraphQL query — fetches the minimum shop data needed at install time.
# ---------------------------------------------------------------------------
_GET_SHOP_INFO_QUERY = """
{
  shop {
    name
    email
    myshopifyDomain
    shopOwnerName: contactEmail
    plan {
      displayName
    }
  }
}
"""


# ---------------------------------------------------------------------------
# ShopifyOAuthService
# Handles the OAuth token exchange and shop info fetch.
# No Django model imports here — keeps this layer thin and testable.
# ---------------------------------------------------------------------------

class ShopifyOAuthService:

    @staticmethod
    def build_auth_url(shop: str) -> str:
        """Returns the Shopify OAuth authorisation redirect URL."""
        return (
            f"https://{shop}/admin/oauth/authorize"
            f"?client_id={settings.SHOPIFY_API_KEY}"
            f"&scope={settings.SHOPIFY_SCOPES}"
            f"&redirect_uri={settings.SHOPIFY_REDIRECT_URI}"
        )

    @staticmethod
    def exchange_code_for_token(shop: str, code: str) -> str:
        """
        Exchanges an OAuth code for a permanent access token.
        Raises ValueError if Shopify returns an error response.
        """
        url = f"https://{shop}/admin/oauth/access_token"
        payload = {
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "code": code,
        }
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()

        if "access_token" not in data:
            logger.error("Shopify token exchange failed for %s: %s", shop, data)
            raise ValueError(f"OAuth token exchange failed: {data.get('error', 'unknown error')}")

        return data["access_token"]

    @staticmethod
    def get_shop_info(shop: str, access_token: str) -> dict:
        """
        Fetches shop metadata via the Storefront GraphQL API.
        Returns the `shop` dict from the GraphQL response.
        Raises ValueError if the request fails or returns GraphQL errors.
        """
        url = f"https://{shop}/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        response = requests.post(
            url,
            headers=headers,
            json={"query": _GET_SHOP_INFO_QUERY},
            timeout=10,
        )
        body = response.json()

        if "errors" in body:
            logger.error("Shopify GraphQL errors for %s: %s", shop, body["errors"])
            raise ValueError(f"Shopify GraphQL error: {body['errors']}")

        return body.get("data", {}).get("shop", {})


# ---------------------------------------------------------------------------
# ShopifyAccountService
# Handles user creation / update and webhook registration.
# All DB writes happen here so views and tasks stay free of model logic.
# ---------------------------------------------------------------------------

class ShopifyAccountService:

    @staticmethod
    @transaction.atomic
    def get_or_create_user(shop: str, access_token: str, shop_data: dict):
        """
        Creates a full Shopify user account on first install, or updates
        the access token on reinstall.

        On first install creates:
          - User (user_type="shopify", is_active=True)
          - AuthProvider (provider="shopify")
          - ShopifyProfile
          - Wallet

        Returns (user, created) where created=True on first install.
        """
        from apps.accounts.models import AuthProvider, ShopifyProfile, User, Wallet

        shop_email = shop_data.get("email", "")
        shop_name = shop_data.get("name", "")

        profile = ShopifyProfile.objects.select_related("user").filter(shop_domain=shop).first()

        if profile:
            # Reinstall — rotate the access token only.
            profile.access_token = access_token
            profile.shop_name = shop_name
            profile.save(update_fields=["access_token", "shop_name"])
            logger.info("ShopifyAccountService: updated token for existing shop %s", shop)
            return profile.user, False

        # First install — create everything.
        user = User.objects.create_user(
            email=shop_email,
            password=None,       # Shopify users never log in with a password
            user_type="shopify",
            is_active=True,
        )

        AuthProvider.objects.create(
            user=user,
            provider="shopify",
            provider_user_id=shop,  # shop domain is the stable unique identifier
        )

        ShopifyProfile.objects.create(
            user=user,
            shop_domain=shop,
            access_token=access_token,
            shop_name=shop_name,
            email=shop_email,
        )

        Wallet.objects.create(user=user)

        logger.info("ShopifyAccountService: created new user for shop %s", shop)
        return user, True

    @staticmethod
    def register_webhooks(shop: str, access_token: str) -> list[dict]:
        """
        Registers the required Shopify webhooks for this app.
        Returns a list of results, one per topic, so the caller can log failures
        without blocking the install flow.

        Topics registered:
          - CUSTOMERS_CREATE  → sync new contacts
          - PRODUCTS_CREATE / UPDATE / DELETE  → product catalogue sync
        """
        webhooks = [{"callback_url":"products/product_webhook","topic":"PRODUCTS_CREATE"},
                                    {"callback_url":"api/customer_create_data_webhook","topic":"CUSTOMERS_CREATE"},
                                    {"callback_url":"products/delete_product_webhook","topic":"PRODUCTS_DELETE"},
                                    {"callback_url":"products/update_product_webhook","topic":"PRODUCTS_UPDATE"}]

        results = []
        for wh in webhooks:
            result = ShopifyAccountService._register_single_webhook(
                shop=shop,
                access_token=access_token,
                topic=wh["topic"],
                callback_url=wh["callback_url"],
            )
            results.append({"topic": wh["topic"], **result})
            if not result["success"]:
                logger.error(
                    "ShopifyAccountService: failed to register webhook %s for %s: %s",
                    wh["topic"], shop, result.get("error"),
                )

        return results

    @staticmethod
    def _register_single_webhook(
        shop: str, access_token: str, topic: str, callback_url: str
    ) -> dict:
        url = f"https://{shop}/admin/api/{settings.SHOPIFY_API_VERSION}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        mutation = """
        mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
          webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
            webhookSubscription {
              id
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "topic": topic,
            "webhookSubscription": {
                "callbackUrl": callback_url,
                "format": "JSON",
            },
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json={"query": mutation, "variables": variables},
                timeout=10,
            )
            body = response.json()
            errors = (
                body.get("data", {})
                .get("webhookSubscriptionCreate", {})
                .get("userErrors", [])
            )
            if errors:
                return {"success": False, "error": errors}
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
