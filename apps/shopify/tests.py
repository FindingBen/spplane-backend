import base64
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import ShopifyProfile, User
from apps.contacts.models import Contact
from apps.shopify.models import (
    ShopifyCustomerLink,
    ShopifyProduct,
    ShopifyProductMedia,
    ShopifyProductVariant,
)
from apps.shopify.service import ShopifyCustomerService, ShopifyGraphQLError


class ShopifyCustomerImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain="merchant.myshopify.com",
            access_token="test-token",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @staticmethod
    def _customer_payload(customer_id, *, phone, first_name="Test", last_name="Customer", email=None):
        return {
            "id": f"gid://shopify/Customer/{customer_id}",
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "marketing_state": "SUBSCRIBED",
            **({"email": email} if email is not None else {}),
        }

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_fetch_customers_does_not_return_email(self, execute_mock):
        execute_mock.return_value = {
            "customers": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Customer/55",
                            "firstName": "Ada",
                            "lastName": "Lovelace",
                            "email": "ada@example.com",
                            "phone": "+15550000055",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "updatedAt": "2026-01-02T00:00:00Z",
                            "defaultPhoneNumber": {"marketingState": "SUBSCRIBED"},
                        }
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }

        payload = ShopifyCustomerService.fetch_customers(self.shopify_profile)

        self.assertEqual(payload["customers"][0]["id"], "gid://shopify/Customer/55")
        self.assertNotIn("email", payload["customers"][0])

    @patch("apps.shopify.service.ShopifyCustomerService.fetch_customers")
    def test_import_endpoint_fetches_all_pages_without_request_payload(self, fetch_customers_mock):
        fetch_customers_mock.side_effect = [
            {
                "customers": [
                    self._customer_payload(1, phone="+15550000001", first_name="Ada", email="ada@example.com"),
                    self._customer_payload(2, phone="", first_name="NoPhone", email="nophone@example.com"),
                ],
                "page_info": {"has_next_page": True, "end_cursor": "cursor-1"},
            },
            {
                "customers": [
                    self._customer_payload(3, phone="+15550000003", first_name="Grace", email="grace@example.com"),
                ],
                "page_info": {"has_next_page": False, "end_cursor": None},
            },
        ]

        response = self.client.post("/api/shopify/customers/import/", {}, format="json")
        self.shopify_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.shopify_profile.first_time_import_customers)
        self.assertEqual(fetch_customers_mock.call_count, 2)
        self.assertEqual(Contact.objects.filter(users=self.user).count(), 2)
        self.assertEqual(
            ShopifyCustomerLink.objects.filter(shopify_profile=self.shopify_profile).count(),
            3,
        )
        first_contact = Contact.objects.get(users=self.user, phone="+15550000001")
        first_link = ShopifyCustomerLink.objects.get(
            shopify_profile=self.shopify_profile,
            shopify_customer_id="gid://shopify/Customer/1",
        )
        self.assertNotIn("email", first_contact.custom_attributes)
        self.assertNotIn("email", first_link.raw_payload)
        self.assertTrue(response.json()["first_time_import_customers"])
        self.assertEqual(
            response.json()["summary"],
            {
                "requested": 3,
                "fetched": 3,
                "imported": 2,
                "skipped": 1,
                "failed": 0,
                "contacts_created": 2,
                "contacts_updated": 0,
                "links_created": 3,
                "links_updated": 0,
            },
        )

    @patch("apps.shopify.service.ShopifyCustomerService.fetch_customers")
    def test_import_endpoint_blocks_second_import_after_first_success(self, fetch_customers_mock):
        fetch_customers_mock.side_effect = [
            {
                "customers": [
                    self._customer_payload(10, phone="+15550000100", first_name="Before", email="before@example.com"),
                ],
                "page_info": {"has_next_page": False, "end_cursor": None},
            }
        ]

        first_response = self.client.post("/api/shopify/customers/import/", {}, format="json")
        self.shopify_profile.refresh_from_db()

        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(self.shopify_profile.first_time_import_customers)
        self.assertEqual(Contact.objects.filter(users=self.user).count(), 1)
        self.assertEqual(ShopifyCustomerLink.objects.filter(shopify_profile=self.shopify_profile).count(), 1)

        fetch_customers_mock.reset_mock()

        second_response = self.client.post("/api/shopify/customers/import/", {}, format="json")

        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(fetch_customers_mock.call_count, 0)
        self.assertEqual(Contact.objects.filter(users=self.user).count(), 1)
        self.assertEqual(ShopifyCustomerLink.objects.filter(shopify_profile=self.shopify_profile).count(), 1)
        self.assertEqual(
            second_response.json()["error"],
            "Customers can be imported only once. Contact support for more info.",
        )

    @patch("apps.shopify.service.ShopifyCustomerService.fetch_customers")
    def test_accounts_me_exposes_import_status_for_frontend(self, fetch_customers_mock):
        me_before_response = self.client.get("/api/accounts/me/")

        self.assertEqual(me_before_response.status_code, 200)
        self.assertFalse(me_before_response.json()["first_time_import_customers"])

        fetch_customers_mock.side_effect = [
            {
                "customers": [
                    self._customer_payload(22, phone="+15550000122", first_name="Grace"),
                ],
                "page_info": {"has_next_page": False, "end_cursor": None},
            }
        ]

        import_response = self.client.post("/api/shopify/customers/import/", {}, format="json")
        me_after_response = self.client.get("/api/accounts/me/")

        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(me_after_response.status_code, 200)
        self.assertTrue(me_after_response.json()["first_time_import_customers"])


@override_settings(SHOPIFY_API_SECRET="webhook-secret")
class ShopifyCustomerWebhookViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="customer-webhook-merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain="customers.myshopify.com",
            access_token="customer-token",
        )
        self.client = APIClient()

    @staticmethod
    def _signed_request_body(payload: dict) -> tuple[bytes, str]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(b"webhook-secret", body, hashlib.sha256).digest()
        return body, base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _webhook_payload(customer_id: int, *, phone: str = "+15550000070", email: str = "ada@example.com"):
        return {
            "id": customer_id,
            "admin_graphql_api_id": f"gid://shopify/Customer/{customer_id}",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": email,
            "phone": phone,
            "sms_marketing_consent": {"state": "subscribed"},
        }

    def test_customer_create_webhook_syncs_customer_without_completing_full_import(self):
        request_body, request_hmac = self._signed_request_body(self._webhook_payload(7))

        response = self.client.generic(
            "POST",
            "/api/shopify/customers/customer_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )
        self.shopify_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.shopify_profile.first_time_import_customers)
        contact = Contact.objects.get(users=self.user, phone="+15550000070")
        link = ShopifyCustomerLink.objects.get(
            shopify_profile=self.shopify_profile,
            shopify_customer_id="gid://shopify/Customer/7",
        )
        self.assertEqual(contact.first_name, "Ada")
        self.assertEqual(link.contact_id, contact.id)
        self.assertNotIn("email", contact.custom_attributes)
        self.assertNotIn("email", link.raw_payload)
        self.assertFalse(response.json()["first_time_import_customers"])
        self.assertEqual(response.json()["summary"]["imported"], 1)
        self.assertEqual(response.json()["results"][0]["status"], "imported")

    def test_customer_create_webhook_returns_400_for_missing_customer_id(self):
        request_body, request_hmac = self._signed_request_body({"first_name": "Broken"})

        response = self.client.generic(
            "POST",
            "/api/shopify/customers/customer_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Webhook payload is missing a customer id.")

    @patch("apps.shopify.apis.views.ShopifyCustomerService.sync_customer_from_webhook", return_value=None)
    def test_customer_create_webhook_returns_500_for_invalid_handler_response(self, sync_customer_mock):
        request_body, request_hmac = self._signed_request_body(self._webhook_payload(8))

        response = self.client.generic(
            "POST",
            "/api/shopify/customers/customer_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "Webhook handler returned an invalid response.")
        self.assertEqual(sync_customer_mock.call_count, 1)

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_delete_customer_webhook(self, execute_mock):
        customer = Contact.objects.create(
            users=self.user,
            first_name="Delete",
            last_name="Me",
            phone="+15550000080",
        )
        link = ShopifyCustomerLink.objects.create(
            shopify_profile=self.shopify_profile,
            shopify_customer_id="gid://shopify/Customer/8",
            contact=customer,
            raw_payload={"id": "gid://shopify/Customer/8"},
        )
        request_body, request_hmac = self._signed_request_body(
            {
                "id": 8,
                "admin_graphql_api_id": "gid://shopify/Customer/8",
                "first_name": "Delete",
                "last_name": "Me",
                "phone": "+15550000080",
            }
        )

        response = self.client.generic(
            "POST",
            "/api/shopify/customers/customer_delete_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )
        customer.refresh_from_db()
        link.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(customer.status, "opted_out")
        self.assertIsNotNone(customer.opted_out_at)
        self.assertIsNotNone(link.deleted_at)
        self.assertEqual(response.json().get("status"), "deleted")
        self.assertEqual(response.json().get("shopify_customer_id"), "gid://shopify/Customer/8")
        self.assertEqual(response.json().get("contact_id"), customer.id)

class ShopifyCatalogModelTests(TestCase):
    def setUp(self):
        self.primary_user = User.objects.create_user(
            email="primary-merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.secondary_user = User.objects.create_user(
            email="secondary-merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.primary_profile = ShopifyProfile.objects.create(
            user=self.primary_user,
            shop_domain="primary.myshopify.com",
            access_token="primary-token",
        )
        self.secondary_profile = ShopifyProfile.objects.create(
            user=self.secondary_user,
            shop_domain="secondary.myshopify.com",
            access_token="secondary-token",
        )

    def test_catalog_models_store_product_variant_and_media_projection(self):
        product = ShopifyProduct.objects.create(
            shopify_profile=self.primary_profile,
            shopify_product_id="gid://shopify/Product/1",
            title="Hero Product",
            handle="hero-product",
            description_html="<p>Hero product description</p>",
            status="ACTIVE",
            tags=["featured", "summer"],
            seo_title="Hero Product SEO",
            seo_description="Hero product SEO description",
            featured_image_url="https://cdn.example.com/product.jpg",
            total_inventory=12,
            has_out_of_stock_variants=False,
            is_gift_card=False,
            variant_count=1,
            media_count=2,
        )
        media = ShopifyProductMedia.objects.create(
            product=product,
            shopify_media_id="gid://shopify/MediaImage/1",
            media_type="image",
            alt_text="Hero product image",
            source_url="https://cdn.example.com/product.jpg",
            preview_image_url="https://cdn.example.com/product-preview.jpg",
            position=1,
            width=1200,
            height=1200,
        )
        variant = ShopifyProductVariant.objects.create(
            product=product,
            shopify_variant_id="gid://shopify/ProductVariant/1",
            title="Default Title",
            sku="HP-001",
            price_amount=Decimal("19.99"),
            inventory_quantity=12,
            position=1,
            shopify_image_id="gid://shopify/ImageSource/1",
            featured_image_url="https://cdn.example.com/product.jpg",
        )

        self.assertEqual(product.variants.count(), 1)
        self.assertEqual(product.media.count(), 1)
        self.assertEqual(product.media.first(), media)
        self.assertEqual(product.variants.first(), variant)

    def test_product_ids_are_unique_per_shopify_profile(self):
        ShopifyProduct.objects.create(
            shopify_profile=self.primary_profile,
            shopify_product_id="gid://shopify/Product/100",
            title="Primary Product",
        )
        ShopifyProduct.objects.create(
            shopify_profile=self.secondary_profile,
            shopify_product_id="gid://shopify/Product/100",
            title="Secondary Product",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShopifyProduct.objects.create(
                    shopify_profile=self.primary_profile,
                    shopify_product_id="gid://shopify/Product/100",
                    title="Duplicate Product",
                )

    def test_variant_and_media_ids_are_unique_within_product(self):
        product = ShopifyProduct.objects.create(
            shopify_profile=self.primary_profile,
            shopify_product_id="gid://shopify/Product/200",
            title="Variant Product",
        )
        ShopifyProductVariant.objects.create(
            product=product,
            shopify_variant_id="gid://shopify/ProductVariant/200",
            title="Red",
        )
        ShopifyProductMedia.objects.create(
            product=product,
            shopify_media_id="gid://shopify/MediaImage/200",
            media_type="image",
            source_url="https://cdn.example.com/red.jpg",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShopifyProductVariant.objects.create(
                    product=product,
                    shopify_variant_id="gid://shopify/ProductVariant/200",
                    title="Duplicate Red",
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShopifyProductMedia.objects.create(
                    product=product,
                    shopify_media_id="gid://shopify/MediaImage/200",
                    media_type="image",
                    source_url="https://cdn.example.com/red-duplicate.jpg",
                )


class ShopifyProductImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="catalog-merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain="catalog.myshopify.com",
            access_token="catalog-token",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @staticmethod
    def _product_payload(product_id, *, title, handle, variant_id, media_id, image_url, price, inventory_quantity):
        return {
            "id": f"gid://shopify/Product/{product_id}",
            "title": title,
            "descriptionHtml": f"<p>{title} description</p>",
            "handle": handle,
            "status": "ACTIVE",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-02T00:00:00Z",
            "hasOutOfStockVariants": inventory_quantity <= 0,
            "isGiftCard": False,
            "publishedAt": "2026-01-03T00:00:00Z",
            "tags": ["featured", "summer"],
            "totalInventory": inventory_quantity,
            "seo": {
                "title": f"{title} SEO",
                "description": f"{title} SEO description",
            },
            "variantsCount": {"count": 1, "precision": "EXACT"},
            "variants": {
                "edges": [
                    {
                        "node": {
                            "id": f"gid://shopify/ProductVariant/{variant_id}",
                            "title": "Default Title",
                            "sku": f"SKU-{variant_id}",
                            "price": price,
                            "inventoryQuantity": inventory_quantity,
                            "image": {
                                "id": f"gid://shopify/ImageSource/{variant_id}",
                                "url": image_url,
                                "altText": f"{title} image",
                            },
                        }
                    }
                ]
            },
            "media": {
                "edges": [
                    {
                        "node": {
                            "mediaContentType": "IMAGE",
                            "id": f"gid://shopify/MediaImage/{media_id}",
                            "alt": f"{title} media",
                            "image": {
                                "id": f"gid://shopify/ImageSource/{media_id}",
                                "url": image_url,
                                "altText": f"{title} media",
                                "width": 1200,
                                "height": 1200,
                            },
                        }
                    }
                ]
            },
        }

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_products_import_endpoint_imports_catalog_across_pages(self, execute_mock):
        execute_mock.side_effect = [
            {
                "products": {
                    "edges": [
                        {
                            "node": self._product_payload(
                                1,
                                title="Hero Product",
                                handle="hero-product",
                                variant_id=11,
                                media_id=21,
                                image_url="https://cdn.example.com/hero.jpg",
                                price="19.99",
                                inventory_quantity=12,
                            )
                        }
                    ],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                }
            },
            {
                "products": {
                    "edges": [
                        {
                            "node": self._product_payload(
                                2,
                                title="Second Product",
                                handle="second-product",
                                variant_id=12,
                                media_id=22,
                                image_url="https://cdn.example.com/second.jpg",
                                price="29.99",
                                inventory_quantity=6,
                            )
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            },
        ]

        response = self.client.post("/api/shopify/products/import/", {}, format="json")
        self.shopify_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(execute_mock.call_count, 2)
        self.assertTrue(self.shopify_profile.connect_products)
        self.assertEqual(ShopifyProduct.objects.filter(shopify_profile=self.shopify_profile).count(), 2)
        self.assertEqual(ShopifyProductVariant.objects.count(), 2)
        self.assertEqual(ShopifyProductMedia.objects.count(), 2)
        hero_product = ShopifyProduct.objects.get(
            shopify_profile=self.shopify_profile,
            shopify_product_id="gid://shopify/Product/1",
        )
        hero_variant = hero_product.variants.get(shopify_variant_id="gid://shopify/ProductVariant/11")
        hero_media = hero_product.media.get(shopify_media_id="gid://shopify/MediaImage/21")
        self.assertEqual(hero_product.featured_image_url, "https://cdn.example.com/hero.jpg")
        self.assertEqual(hero_variant.price_amount, Decimal("19.99"))
        self.assertEqual(hero_media.source_url, "https://cdn.example.com/hero.jpg")
        self.assertEqual(
            response.json()["summary"],
            {
                "requested": 2,
                "fetched": 2,
                "products_created": 2,
                "products_updated": 0,
                "products_deleted": 0,
                "variants_created": 2,
                "variants_updated": 0,
                "variants_deleted": 0,
                "media_created": 2,
                "media_updated": 0,
                "media_deleted": 0,
            },
        )
        self.assertTrue(response.json()["connect_products"])

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_products_import_endpoint_blocks_second_import_after_first_success(self, execute_mock):
        execute_mock.side_effect = [
            {
                "products": {
                    "edges": [
                        {
                            "node": self._product_payload(
                                10,
                                title="Delete Me",
                                handle="delete-me",
                                variant_id=110,
                                media_id=210,
                                image_url="https://cdn.example.com/delete.jpg",
                                price="9.99",
                                inventory_quantity=2,
                            )
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            },
        ]

        first_response = self.client.post("/api/shopify/products/import/", {}, format="json")
        self.shopify_profile.refresh_from_db()
        execute_mock.reset_mock()
        second_response = self.client.post("/api/shopify/products/import/", {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(self.shopify_profile.connect_products)
        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(execute_mock.call_count, 0)
        self.assertEqual(
            second_response.json()["error"],
            "Products can be imported only once. Future product changes sync via webhooks.",
        )

    def test_products_list_endpoint_returns_local_catalog_projection(self):
        product = ShopifyProduct.objects.create(
            shopify_profile=self.shopify_profile,
            shopify_product_id="gid://shopify/Product/300",
            title="Builder Hero",
            handle="builder-hero",
            description_html="<p>Builder Hero description</p>",
            status="ACTIVE",
            tags=["builder"],
            featured_image_url="https://cdn.example.com/builder.jpg",
            total_inventory=14,
            variant_count=1,
            media_count=1,
        )
        ShopifyProductVariant.objects.create(
            product=product,
            shopify_variant_id="gid://shopify/ProductVariant/300",
            title="Default Title",
            sku="BUILDER-300",
            price_amount=Decimal("49.99"),
            inventory_quantity=14,
            position=1,
            featured_image_url="https://cdn.example.com/builder.jpg",
        )
        ShopifyProductMedia.objects.create(
            product=product,
            shopify_media_id="gid://shopify/MediaImage/300",
            media_type="image",
            source_url="https://cdn.example.com/builder.jpg",
            preview_image_url="https://cdn.example.com/builder.jpg",
            position=1,
        )

        response = self.client.get("/api/shopify/products/?search=Builder")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page_info"], {"has_next_page": False, "returned": 1, "total_count": 1})
        self.assertEqual(payload["products"][0]["shopify_product_id"], "gid://shopify/Product/300")
        self.assertEqual(payload["products"][0]["variants"][0]["sku"], "BUILDER-300")
        self.assertEqual(payload["products"][0]["media"][0]["source_url"], "https://cdn.example.com/builder.jpg")


@override_settings(SHOPIFY_API_SECRET="webhook-secret")
class ShopifyProductWebhookViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="webhook-merchant@example.com",
            password="password123",
            user_type="shopify",
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain="catalog.myshopify.com",
            access_token="catalog-token",
        )
        self.client = APIClient()

    @staticmethod
    def _signed_request_body(payload: dict) -> tuple[bytes, str]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(b"webhook-secret", body, hashlib.sha256).digest()
        return body, base64.b64encode(digest).decode("utf-8")

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_create_product_webhook_syncs_product_from_graphql_projection(self, execute_mock):
        execute_mock.return_value = {
            "product": ShopifyProductImportViewTests._product_payload(
                1,
                title="Webhook Product",
                handle="webhook-product",
                variant_id=11,
                media_id=21,
                image_url="https://cdn.example.com/webhook.jpg",
                price="39.99",
                inventory_quantity=8,
            )
        }
        request_body, request_hmac = self._signed_request_body(
            {
                "id": 1,
                "admin_graphql_api_id": "gid://shopify/Product/1",
                "title": "Webhook Product",
            }
        )

        response = self.client.generic(
            "POST",
            "/api/shopify/products/product_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )
        self.shopify_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.shopify_profile.connect_products)
        self.assertEqual(execute_mock.call_count, 1)
        self.assertEqual(execute_mock.call_args.kwargs["variables"]["id"], "gid://shopify/Product/1")
        product = ShopifyProduct.objects.get(
            shopify_profile=self.shopify_profile,
            shopify_product_id="gid://shopify/Product/1",
        )
        self.assertEqual(product.title, "Webhook Product")
        self.assertEqual(product.variants.get().sku, "SKU-11")
        self.assertEqual(product.media.get().source_url, "https://cdn.example.com/webhook.jpg")
        self.assertTrue(response.json()["connect_products"])

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_update_product_webhook_syncs_product_from_graphql_projection(self, execute_mock):
        execute_mock.return_value = {
            "product": ShopifyProductImportViewTests._product_payload(
                2,
                title="Updated Webhook Product",
                handle="updated-webhook-product",
                variant_id=22,
                media_id=32,
                image_url="https://cdn.example.com/updated-webhook.jpg",
                price="49.99",
                inventory_quantity=5,
            )
        }
        request_body, request_hmac = self._signed_request_body(
            {
                "id": 2,
                "admin_graphql_api_id": "gid://shopify/Product/2",
                "title": "Updated Webhook Product",
            }
        )

        response = self.client.generic(
            "POST",
            "/api/shopify/products/update_product_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )
        self.shopify_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.shopify_profile.connect_products)
        self.assertEqual(execute_mock.call_count, 1)
        self.assertEqual(execute_mock.call_args.kwargs["variables"]["id"], "gid://shopify/Product/2")
        product = ShopifyProduct.objects.get(
            shopify_profile=self.shopify_profile,
            shopify_product_id="gid://shopify/Product/2",
        )
        self.assertEqual(product.title, "Updated Webhook Product")
        self.assertEqual(product.variants.get().sku, "SKU-22")
        self.assertEqual(product.media.get().source_url, "https://cdn.example.com/updated-webhook.jpg")
        self.assertTrue(response.json()["connect_products"])

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_delete_product_webhook_marks_local_projection_deleted(self, execute_mock):
        product = ShopifyProduct.objects.create(
            shopify_profile=self.shopify_profile,
            shopify_product_id="gid://shopify/Product/3",
            title="Delete Me",
            handle="delete-me",
            status="ACTIVE",
            featured_image_url="https://cdn.example.com/delete-me.jpg",
            total_inventory=3,
            variant_count=1,
            media_count=1,
        )
        variant = ShopifyProductVariant.objects.create(
            product=product,
            shopify_variant_id="gid://shopify/ProductVariant/33",
            title="Default Title",
            sku="SKU-33",
            price_amount=Decimal("9.99"),
            inventory_quantity=3,
            position=1,
            featured_image_url="https://cdn.example.com/delete-me.jpg",
        )
        media = ShopifyProductMedia.objects.create(
            product=product,
            shopify_media_id="gid://shopify/MediaImage/43",
            media_type="image",
            source_url="https://cdn.example.com/delete-me.jpg",
            preview_image_url="https://cdn.example.com/delete-me.jpg",
            position=1,
        )
        request_body, request_hmac = self._signed_request_body(
            {
                "id": 3,
                "admin_graphql_api_id": "gid://shopify/Product/3",
                "title": "Delete Me",
            }
        )

        response = self.client.generic(
            "POST",
            "/api/shopify/products/delete_product_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )
        self.shopify_profile.refresh_from_db()
        product.refresh_from_db()
        variant.refresh_from_db()
        media.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(execute_mock.call_count, 0)
        self.assertTrue(self.shopify_profile.connect_products)
        self.assertIsNotNone(product.deleted_at)
        self.assertIsNotNone(variant.deleted_at)
        self.assertIsNotNone(media.deleted_at)
        self.assertEqual(response.json()["summary"]["products_deleted"], 1)
        self.assertEqual(response.json()["summary"]["variants_deleted"], 1)
        self.assertEqual(response.json()["summary"]["media_deleted"], 1)
        self.assertTrue(response.json()["connect_products"])

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_create_product_webhook_rejects_invalid_hmac(self, execute_mock):
        request_body, _ = self._signed_request_body({"id": 1})

        response = self.client.generic(
            "POST",
            "/api/shopify/products/product_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256="invalid",
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "Invalid HMAC signature.")
        self.assertEqual(execute_mock.call_count, 0)

    @patch("apps.shopify.service.ShopifyGraphQLClient.execute")
    def test_create_product_webhook_returns_502_when_graphql_sync_fails(self, execute_mock):
        execute_mock.side_effect = ShopifyGraphQLError("Shopify GraphQL error: upstream failure")
        request_body, request_hmac = self._signed_request_body(
            {
                "id": 4,
                "admin_graphql_api_id": "gid://shopify/Product/4",
                "title": "Broken Product",
            }
        )

        response = self.client.generic(
            "POST",
            "/api/shopify/products/product_webhook",
            request_body,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=request_hmac,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=self.shopify_profile.shop_domain,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "Shopify GraphQL error: upstream failure")