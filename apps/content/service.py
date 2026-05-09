import copy
import os
import uuid

from apps.content.models import Template, Content
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage


class ContentService:
    @staticmethod
    def create_content(user, template_id, structure, files=None):
        """Create content from template"""
        upload_payload = ContentService.upload_content(user, template_id, structure, files=files)

        content = Content.objects.create(
            user=user,
            template=upload_payload['template'],
            structure=upload_payload['structure']
        )

        return content

    @staticmethod
    def upload_content(user, template_id, structure, files=None):
        """Upload image/video files and return the final structure with media URLs."""
        ContentService._validate_template_exists(template_id)
        ContentService._validate_structure(structure)

        template = Template.objects.get(id=template_id)
        updated_structure = ContentService._attach_uploaded_media(
            user,
            structure,
            files=files,
        )
        media_urls = ContentService._extract_media_urls(updated_structure)

        return {
            'template': template,
            'structure': updated_structure,
            'media_urls': media_urls,
        }

    @staticmethod
    def get_user_contents(user):
        """Get all content for a user"""
        return Content.objects.filter(user=user)

    @staticmethod
    def _validate_template_exists(template_id):
        """Check template exists"""
        if not Template.objects.filter(id=template_id).exists():
            raise ValidationError(f"Template with id {template_id} not found")

    @staticmethod
    def _validate_structure(structure):
        """Validate content structure"""
        if not isinstance(structure, dict):
            raise ValidationError("Structure must be a JSON object")

    @staticmethod
    def _extract_media_urls(structure):
        """Collect image and video URLs already uploaded by the frontend."""
        components = structure.get('components', [])
        media_urls = {
            'images': [],
            'videos': [],
        }

        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue

            props = component.get('props', {})
            if not isinstance(props, dict):
                continue

            component_id = component.get('id') or f'component_{index}'
            component_type = component.get('type')

            if component_type == 'image':
                image_url = props.get('src') or props.get('url')
                if image_url:
                    media_urls['images'].append({
                        'component_id': component_id,
                        'url': image_url,
                    })

            if component_type == 'video':
                playback_url = props.get('playbackUrl') or props.get('src') or props.get('url')
                poster_url = props.get('posterUrl') or props.get('poster')
                if playback_url or poster_url:
                    media_urls['videos'].append({
                        'component_id': component_id,
                        'playback_url': playback_url,
                        'poster_url': poster_url,
                    })

        return media_urls

    @staticmethod
    def _attach_uploaded_media(user, structure, files=None):
        """Save uploaded media files and inject their URLs into the content structure."""
        if not files:
            return copy.deepcopy(structure)

        updated_structure = copy.deepcopy(structure)
        components = updated_structure.get('components', [])

        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue

            props = component.get('props', {})
            if not isinstance(props, dict):
                continue

            component_type = component.get('type')
            component_id = component.get('id') or f'component_{index}'
            upload_field = props.get('uploadField') or component_id

            if component_type == 'image':
                image_file = files.get(upload_field)
                if image_file:
                    saved_media = ContentService._save_uploaded_file(user, image_file, 'images')
                    props['src'] = saved_media['url']
                    props['storageKey'] = saved_media['storage_key']

            if component_type == 'video':
                video_file = files.get(upload_field)
                if video_file:
                    saved_media = ContentService._save_uploaded_file(user, video_file, 'videos')
                    props['playbackUrl'] = saved_media['url']
                    props['storageKey'] = saved_media['storage_key']
                    props['mimeType'] = video_file.content_type or props.get('mimeType')

                poster_field = props.get('posterUploadField') or f'{upload_field}__poster'
                poster_file = files.get(poster_field)
                if poster_file:
                    saved_poster = ContentService._save_uploaded_file(user, poster_file, 'video-posters')
                    props['posterUrl'] = saved_poster['url']
                    props['posterStorageKey'] = saved_poster['storage_key']

        return updated_structure

    @staticmethod
    def _save_uploaded_file(user, uploaded_file, folder):
        """Persist an uploaded file using the configured default storage backend."""
        file_extension = os.path.splitext(uploaded_file.name or '')[1]
        storage_key = os.path.join(
            'content',
            str(user.id),
            folder,
            f'{uuid.uuid4().hex}{file_extension}',
        ).replace('\\', '/')
        saved_path = default_storage.save(storage_key, uploaded_file)

        return {
            'storage_key': saved_path,
            'url': default_storage.url(saved_path),
        }
