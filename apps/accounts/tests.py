from django.test import TestCase

from config.settings import _build_trusted_origins


class TrustedOriginsSettingsTests(TestCase):
	def test_frontend_url_is_added_to_trusted_origins(self):
		origins = _build_trusted_origins(
			'https://spplane.app/dashboard',
			'http://localhost:5173,http://127.0.0.1:5173',
		)

		self.assertEqual(
			origins,
			[
				'http://localhost:5173',
				'http://127.0.0.1:5173',
				'https://spplane.app',
			],
		)

	def test_invalid_origins_are_ignored_and_duplicates_removed(self):
		origins = _build_trusted_origins(
			'https://spplane.app',
			'https://spplane.app,not-an-origin,https://spplane.app/path',
		)

		self.assertEqual(origins, ['https://spplane.app'])
