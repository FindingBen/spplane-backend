import json
import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils.datastructures import MultiValueDict
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.content.apis.views import ContentViewSet
from apps.content.models import Content, Template
from apps.content.service import ContentService


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
