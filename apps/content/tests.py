import json
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils.datastructures import MultiValueDict
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import ShopifyProfile, User
from apps.content.apis.views import ContentViewSet
from apps.content.llm import ProductCopyPayload
from apps.content.models import Content, Template
from apps.content.service import ContentService, ProductContentGenerationService
from apps.shopify.models import ShopifyProduct


class ContentUploadServiceTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email='builder@example.com',
			password='pass12345',
			user_type='regular',
		)
		self.template = Template.objects.create(
			name='Media Template',
			description='Template with uploadable media blocks',
			category='landing_page',
			structure={
				'version': 1,
				'components': [
					{'id': 'hero-image', 'type': 'image', 'props': {}},
					{'id': 'hero-video', 'type': 'video', 'props': {}},
				],
			},
			is_active=True,
		)
		self.temp_media = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_media.cleanup)
		self.api_factory = APIRequestFactory()

	def test_create_content_uploads_image_and_rewrites_structure(self):
		structure = {
			'version': 1,
			'components': [
				{
					'id': 'hero-image',
					'type': 'image',
					'props': {
						'uploadField': 'hero-image',
						'alt': 'Campaign hero',
					},
				},
			],
		}
		files = MultiValueDict({
			'hero-image': [
				SimpleUploadedFile('banner.jpg', b'image-bytes', content_type='image/jpeg'),
			],
		})

		with self.settings(MEDIA_ROOT=self.temp_media.name, MEDIA_URL='/media/'):
			content = ContentService.create_content(
				self.user,
				self.template.id,
				structure,
				files=files,
			)

		props = content.structure['components'][0]['props']
		self.assertTrue(props['src'].startswith('/media/content/'))
		self.assertTrue(props['storageKey'].startswith(f'content/{self.user.id}/images/'))
		self.assertEqual(props['alt'], 'Campaign hero')

	def test_create_content_adds_props_when_component_props_missing(self):
		structure = {
			'version': 1,
			'components': [
				{
					'id': 'hero-image',
					'type': 'image',
				},
			],
		}
		files = MultiValueDict({
			'hero-image': [
				SimpleUploadedFile('banner.jpg', b'image-bytes', content_type='image/jpeg'),
			],
		})

		with self.settings(MEDIA_ROOT=self.temp_media.name, MEDIA_URL='/media/'):
			content = ContentService.create_content(
				self.user,
				self.template.id,
				structure,
				files=files,
			)

		props = content.structure['components'][0]['props']
		self.assertTrue(props['src'].startswith('/media/content/'))
		self.assertTrue(props['storageKey'].startswith(f'content/{self.user.id}/images/'))

	def test_create_content_uploads_image_using_nested_image_upload_field(self):
		structure = {
			'version': 1,
			'components': [
				{
					'id': 'product-image',
					'type': 'image',
					'props': {
						'alt': 'Product image',
						'image': '',
						'uploadFields': {
							'image': {
								'uploadField': 'image-file-3',
							},
						},
					},
				},
			],
		}
		files = MultiValueDict({
			'image-file-3': [
				SimpleUploadedFile('product.jpg', b'image-bytes', content_type='image/jpeg'),
			],
		})

		with self.settings(MEDIA_ROOT=self.temp_media.name, MEDIA_URL='/media/'):
			content = ContentService.create_content(
				self.user,
				self.template.id,
				structure,
				files=files,
			)

		props = content.structure['components'][0]['props']
		self.assertTrue(props['image'].startswith('/media/content/'))
		self.assertTrue(props['storageKey'].startswith(f'content/{self.user.id}/images/'))

	def test_create_content_uploads_video_and_poster_and_keeps_metadata(self):
		structure = {
			'version': 1,
			'components': [
				{
					'id': 'hero-video',
					'type': 'video',
					'props': {
						'uploadField': 'hero-video',
						'posterUploadField': 'hero-video__poster',
						'duration': 42.6,
						'aspectRatio': '16:9',
					},
				},
			],
		}
		files = MultiValueDict({
			'hero-video': [
				SimpleUploadedFile('clip.mp4', b'video-bytes', content_type='video/mp4'),
			],
			'hero-video__poster': [
				SimpleUploadedFile('poster.jpg', b'poster-bytes', content_type='image/jpeg'),
			],
		})

		with self.settings(MEDIA_ROOT=self.temp_media.name, MEDIA_URL='/media/'):
			content = ContentService.create_content(
				self.user,
				self.template.id,
				structure,
				files=files,
			)

		props = content.structure['components'][0]['props']
		self.assertTrue(props['playbackUrl'].startswith('/media/content/'))
		self.assertTrue(props['posterUrl'].startswith('/media/content/'))
		self.assertTrue(props['storageKey'].startswith(f'content/{self.user.id}/videos/'))
		self.assertTrue(props['posterStorageKey'].startswith(f'content/{self.user.id}/video-posters/'))
		self.assertEqual(props['mimeType'], 'video/mp4')
		self.assertEqual(props['duration'], 42.6)
		self.assertEqual(props['aspectRatio'], '16:9')

	def test_partial_update_uploads_image_and_rewrites_structure(self):
		content = Content.objects.create(
			user=self.user,
			template=self.template,
			structure={
				'version': 1,
				'components': [
					{
						'id': 'hero-image',
						'type': 'image',
						'props': {
							'uploadField': 'hero-image',
						},
					},
				],
			},
		)
		request = self.api_factory.patch(
			'/api/content/v1/{}/'.format(content.id),
			{
				'structure': json.dumps(content.structure),
				'hero-image': SimpleUploadedFile('banner.jpg', b'image-bytes', content_type='image/jpeg'),
			},
			format='multipart',
		)
		force_authenticate(request, user=self.user)
		view = ContentViewSet.as_view({'patch': 'partial_update'})

		with self.settings(MEDIA_ROOT=self.temp_media.name, MEDIA_URL='/media/'):
			response = view(request, pk=content.pk)

		content.refresh_from_db()
		props = content.structure['components'][0]['props']
		self.assertEqual(response.status_code, 200)
		self.assertTrue(props['src'].startswith('/media/content/'))
		self.assertTrue(props['storageKey'].startswith(f'content/{self.user.id}/images/'))


class ProductContentGenerationServiceTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email='shopify-builder@example.com',
			password='pass12345',
			user_type='shopify',
		)
		self.shopify_profile = ShopifyProfile.objects.create(
			user=self.user,
			shop_domain='catalog.myshopify.com',
			access_token='token',
		)
		self.template = Template.objects.create(
			name='Generated Landing Template',
			description='Template for generated product content',
			category='landing_page',
			structure={
				'version': 1,
				'components': [
					{'id': 'hero-title', 'type': 'text', 'props': {}},
					{'id': 'hero-subtitle', 'type': 'text', 'props': {}},
					{'id': 'hero-image', 'type': 'image', 'props': {}},
					{'id': 'product-price', 'type': 'text', 'props': {}},
					{'id': 'inventory-urgency', 'type': 'text', 'props': {}},
					{'id': 'variant-options', 'type': 'text', 'props': {}},
					{'id': 'gallery', 'type': 'gallery', 'props': {}},
					{'id': 'primary-cta', 'type': 'cta', 'props': {}},
				],
			},
			is_active=True,
		)
		self.product = ShopifyProduct.objects.create(
			shopify_profile=self.shopify_profile,
			shopify_product_id='gid://shopify/Product/100',
			title='Portable shoulder massager',
			handle='portable-shoulder-massager',
			status='ACTIVE',
			tags=['recovery', 'wellness'],
			featured_image_url='https://cdn.example.com/hero.jpg',
			total_inventory=6,
			variant_count=2,
			media_count=3,
			raw_payload={
				'id': 'gid://shopify/Product/100',
				'title': 'Portable shoulder massager',
				'handle': 'portable-shoulder-massager',
				'status': 'ACTIVE',
				'tags': ['recovery', 'wellness'],
				'seo': {
					'title': 'Portable shoulder massager',
					'description': 'Relieve shoulder tension at home or on the go.',
				},
				'totalInventory': 6,
				'hasOutOfStockVariants': False,
				'descriptionHtml': '<p>Relieve shoulder tension at home or on the go.</p>',
				'variantsCount': {'count': 2, 'precision': 'EXACT'},
				'media': {
					'edges': [
						{
							'node': {
								'id': 'gid://shopify/MediaImage/1',
								'alt': 'Hero image',
								'mediaContentType': 'IMAGE',
								'image': {
									'id': 'gid://shopify/ImageSource/1',
									'url': 'https://cdn.example.com/hero.jpg',
									'altText': 'Hero image',
									'width': 1200,
									'height': 1200,
								},
							},
						},
						{
							'node': {
								'id': 'gid://shopify/MediaImage/2',
								'alt': 'Lifestyle image',
								'mediaContentType': 'IMAGE',
								'image': {
									'id': 'gid://shopify/ImageSource/2',
									'url': 'https://cdn.example.com/lifestyle.jpg',
									'altText': 'Lifestyle image',
									'width': 1200,
									'height': 1200,
								},
							},
						},
						{
							'node': {
								'id': 'gid://shopify/MediaImage/3',
								'alt': 'Close-up image',
								'mediaContentType': 'IMAGE',
								'image': {
									'id': 'gid://shopify/ImageSource/3',
									'url': 'https://cdn.example.com/detail.jpg',
									'altText': 'Close-up image',
									'width': 1200,
									'height': 1200,
								},
							},
						},
					],
				},
				'variants': {
					'edges': [
						{
							'node': {
								'id': 'gid://shopify/ProductVariant/1',
								'title': 'Standard',
								'sku': 'STD',
								'price': '39.99',
								'inventoryQuantity': 4,
								'image': {
									'id': 'gid://shopify/ProductImage/1',
									'url': 'https://cdn.example.com/hero.jpg',
									'altText': 'Standard image',
								},
							},
						},
						{
							'node': {
								'id': 'gid://shopify/ProductVariant/2',
								'title': 'Deluxe',
								'sku': 'DLX',
								'price': '49.99',
								'inventoryQuantity': 2,
								'image': {
									'id': 'gid://shopify/ProductImage/2',
									'url': 'https://cdn.example.com/detail.jpg',
									'altText': 'Deluxe image',
								},
							},
						},
					],
				},
			},
		)

	@patch('apps.content.service.build_llm_client')
	def test_generate_content_for_product_populates_existing_template_structure(self, build_llm_client_mock):
		class StubLLMClient:
			provider_name = 'stub'

			def generate_product_copy(self, *, product_data, rule_analysis, template_structure):
				del product_data, rule_analysis, template_structure
				return ProductCopyPayload(
					hero_title='Get rid of shoulder pain',
					hero_subtitle='Portable relief built for daily use.',
					pain_point='Ease shoulder discomfort wherever the day takes you.',
					benefit_bullets=['Portable design', 'Targeted shoulder support'],
					cta_label='Buy now',
					urgency_message='Only 6 units left in stock.',
					bundle_headline='Choose your option',
					bundle_items=['Standard', 'Deluxe'],
					price_caption='From $39.99 to $49.99',
					tag_line='recovery, wellness',
				)

		build_llm_client_mock.return_value = StubLLMClient()

		result = ProductContentGenerationService.generate_content_for_product(
			user=self.user,
			product_id=self.product.id,
			template_id=self.template.id,
			persist=False,
		)

		components = result['structure']['components']
		self.assertEqual(result['llm_provider'], 'stub')
		self.assertEqual(components[0]['props']['title'], 'Get rid of shoulder pain')
		self.assertEqual(components[1]['props']['subtitle'], 'Portable relief built for daily use.')
		self.assertEqual(components[2]['props']['src'], 'https://cdn.example.com/hero.jpg')
		self.assertEqual(components[3]['props']['text'], 'From $39.99 to $49.99')
		self.assertEqual(components[4]['props']['text'], 'Only 6 units left in stock.')
		self.assertEqual(len(components[5]['props']['items']), 2)
		self.assertEqual(len(components[6]['props']['images']), 3)
		self.assertEqual(components[7]['props']['label'], 'Buy now')
		self.assertEqual(components[7]['props']['url'], 'https://catalog.myshopify.com/products/portable-shoulder-massager')
