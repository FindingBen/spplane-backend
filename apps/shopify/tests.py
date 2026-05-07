from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import ShopifyProfile, User
from apps.contacts.models import Contact
from apps.shopify.models import ShopifyCustomerLink
from apps.shopify.service import ShopifyCustomerService


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
