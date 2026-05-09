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
    def update_content(content, template_id, structure, files=None):
        """Update existing content and attach any newly uploaded media."""
        upload_payload = ContentService.upload_content(
            content.user,
            template_id,
            structure,
            files=files,
        )

        content.template = upload_payload['template']
        content.structure = upload_payload['structure']
        content.save()

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
        blocks = structure.get('blocks', []) or structure.get('components', [])
        media_urls = {
            'images': [],
            'videos': [],
        }

        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue

            props = block.get('props', {})
            if not isinstance(props, dict):
                continue

            block_id = block.get('id') or f'block_{index}'
            block_type = block.get('type')

            if block_type in ('image-hero', 'image'):
                image_url = props.get('fallbackImage') or props.get('imageUrl') or props.get('src') or props.get('url')
                if image_url:
                    media_urls['images'].append({
                        'block_id': block_id,
                        'url': image_url,
                    })

            if block_type in ('video-hero', 'video'):
                playback_url = props.get('videoUrl') or props.get('playbackUrl') or props.get('src') or props.get('url')
                poster_url = props.get('posterUrl') or props.get('poster')
                if playback_url or poster_url:
                    media_urls['videos'].append({
                        'block_id': block_id,
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
        blocks = updated_structure.get('blocks') or updated_structure.get('components', [])

        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue

            props = block.get('props')
            if props is None:
                props = {}
                block['props'] = props
            elif not isinstance(props, dict):
                continue

            block_type = block.get('type')
            block_id = block.get('id') or f'block_{index}'
            
            # Extract upload fields from nested uploadFields structure
            upload_fields_map = props.get('uploadFields', {})

            if block_type in ('image-hero', 'image'):
                # Try to get image upload field from uploadFields, fallback to uploadField, then block_id
                image_upload_key = upload_fields_map.get('fallbackImage') or upload_fields_map.get('imageUrl')
                upload_field = (image_upload_key.get('uploadField') if isinstance(image_upload_key, dict) else None) or props.get('uploadField') or block_id
                
                image_file = files.get(upload_field)
                if image_file:
                    saved_media = ContentService._save_uploaded_file(user, image_file, 'images')
                    if block_type == 'image-hero' or 'fallbackImage' in props:
                        props['fallbackImage'] = saved_media['url']
                    elif 'imageUrl' in props:
                        props['imageUrl'] = saved_media['url']
                    else:
                        props['src'] = saved_media['url']
                    props['storageKey'] = saved_media['storage_key']

            if block_type in ('video-hero', 'video'):
                # Try to get video upload field from uploadFields, fallback to uploadField, then block_id
                video_upload_key = upload_fields_map.get('videoUrl')
                upload_field = (video_upload_key.get('uploadField') if isinstance(video_upload_key, dict) else None) or props.get('uploadField') or block_id
                
                video_file = files.get(upload_field)
                if video_file:
                    saved_media = ContentService._save_uploaded_file(user, video_file, 'videos')
                    if block_type == 'video-hero' or 'videoUrl' in props:
                        props['videoUrl'] = saved_media['url']
                    else:
                        props['playbackUrl'] = saved_media['url']
                    props['storageKey'] = saved_media['storage_key']
                    props['mimeType'] = video_file.content_type or props.get('mimeType')

                poster_upload_key = upload_fields_map.get('posterUrl')
                poster_field = (poster_upload_key.get('uploadField') if isinstance(poster_upload_key, dict) else None) or props.get('posterUploadField') or f'{upload_field}__poster'
                
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
