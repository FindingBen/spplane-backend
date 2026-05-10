import copy
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation

from apps.content.models import Template, Content
from apps.content.llm import ProductCopyPayload, build_llm_client
from apps.content.rules import ProductRuleEngine
from apps.shopify.models import ShopifyProduct as Sh
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.utils.html import strip_tags


logger = logging.getLogger(__name__)

DEFAULT_PRODUCT_CONTENT_TEMPLATE_ID = 1


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
                image_url = (
                    props.get('fallbackImage')
                    or props.get('imageUrl')
                    or props.get('image')
                    or props.get('src')
                    or props.get('url')
                )
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
                image_upload_key = (
                    upload_fields_map.get('fallbackImage')
                    or upload_fields_map.get('imageUrl')
                    or upload_fields_map.get('image')
                )
                upload_field = (image_upload_key.get('uploadField') if isinstance(image_upload_key, dict) else None) or props.get('uploadField') or block_id
                
                image_file = files.get(upload_field)
                if image_file:
                    saved_media = ContentService._save_uploaded_file(user, image_file, 'images')
                    if block_type == 'image-hero' or 'fallbackImage' in props:
                        props['fallbackImage'] = saved_media['url']
                    elif 'imageUrl' in props:
                        props['imageUrl'] = saved_media['url']
                    elif 'image' in props:
                        props['image'] = saved_media['url']
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


class ProductContentGenerationService:
    """Service for generating content based on product data"""
    @staticmethod
    def generate_content_for_product(*, user, product_id, template_id=None, persist=True):
        product = ProductContentGenerationService._get_user_product(user=user, product_id=product_id)
        template = ProductContentGenerationService._resolve_template(template_id)
        normalized_data = ProductContentGenerationService.normalize_product_data(product)
        rule_analysis = ProductRuleEngine.analyze(normalized_data)

        llm_client = build_llm_client()
        copy_payload = llm_client.generate_product_copy(
            product_data=normalized_data,
            rule_analysis=rule_analysis,
            template_structure=template.structure,
        )
        generated_structure = ProductContentGenerationService._populate_template_structure(
            template_structure=template.structure,
            product_data=normalized_data,
            rule_analysis=rule_analysis,
            copy_payload=copy_payload,
            llm_provider=llm_client.provider_name,
        )

        content = None
        if persist:
            content = ContentService.create_content(
                user=user,
                template_id=template.id,
                structure=generated_structure,
            )

        return {
            'content': content,
            'copy': copy_payload.model_dump(),
            'llm_provider': llm_client.provider_name,
            'product': normalized_data,
            'rules': rule_analysis,
            'structure': generated_structure,
            'template': template,
        }


    @staticmethod
    def normalize_product_data(product) -> dict:
        """Extract and normalize relevant product data for content generation"""
        raw_payload = product.raw_payload or {}
        seo = raw_payload.get('seo') or {}
        media_edges = (raw_payload.get('media') or {}).get('edges') or []
        variant_edges = (raw_payload.get('variants') or {}).get('edges') or []
        variants_count = raw_payload.get('variantsCount') or {}
        description_html = raw_payload.get('descriptionHtml') or product.description_html
        description_text = strip_tags(description_html or '').strip()

        media = []
        images = []
        for edge in media_edges:
            node = edge.get('node') or {}
            image = node.get('image') or {}
            image_url = image.get('url') or ''

            media_item = {
                'id': node.get('id'),
                'alt': node.get('alt'),
                'media_content_type': node.get('mediaContentType'),
                'image_id': image.get('id'),
                'image_url': image_url,
                'image_width': image.get('width'),
                'image_height': image.get('height'),
                'image_alt_text': image.get('altText'),
            }
            media.append(media_item)

            if image_url:
                images.append(image_url)

        variants = []
        for edge in variant_edges:
            node = edge.get('node') or {}
            image = node.get('image') or {}
            variants.append(
                {
                    'id': node.get('id'),
                    'title': node.get('title'),
                    'sku': node.get('sku'),
                    'price': node.get('price'),
                    'inventory_quantity': node.get('inventoryQuantity'),
                    'image_id': image.get('id'),
                    'image_url': image.get('url'),
                    'image_alt_text': image.get('altText'),
                }
            )

        featured_image_url = images[0] if images else ''
        if not featured_image_url and variants:
            featured_image_url = variants[0].get('image_url') or ''

        prices = []
        for variant in variants:
            price = ProductContentGenerationService._coerce_decimal(variant.get('price'))
            if price is not None:
                prices.append(price)

        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        shop_domain = getattr(product.shopify_profile, 'shop_domain', '')
        handle = raw_payload.get('handle') or product.handle
        product_url = f"https://{shop_domain}/products/{handle}" if shop_domain and handle else ''

        return {
            'db_id': product.id,
            'id': raw_payload.get('id') or product.shopify_product_id,
            'title': raw_payload.get('title') or product.title,
            'handle': handle,
            'shop_domain': shop_domain,
            'product_url': product_url,
            'status': raw_payload.get('status') or product.status,
            'description_html': description_html,
            'description_text': description_text,
            'seo_title': seo.get('title') or product.seo_title,
            'seo_description': seo.get('description') or product.seo_description,
            'tags': raw_payload.get('tags') or product.tags,
            'created_at': raw_payload.get('createdAt'),
            'updated_at': raw_payload.get('updatedAt'),
            'published_at': raw_payload.get('publishedAt'),
            'is_gift_card': raw_payload.get('isGiftCard', product.is_gift_card),
            'total_inventory': raw_payload.get('totalInventory', product.total_inventory),
            'has_out_of_stock_variants': raw_payload.get(
                'hasOutOfStockVariants',
                product.has_out_of_stock_variants,
            ),
            'variants_count': variants_count.get('count', product.variant_count),
            'variants_count_precision': variants_count.get('precision'),
            'featured_image_url': featured_image_url or product.featured_image_url,
            'primary_variant': variants[0] if variants else None,
            'price_min': f"{min_price:.2f}" if min_price is not None else None,
            'price_max': f"{max_price:.2f}" if max_price is not None else None,
            'images': images,
            'media': media,
            'raw_payload': raw_payload,
            'variants': variants,
        }

    @staticmethod
    def _get_user_product(*, user, product_id):
        product = Sh.objects.select_related('shopify_profile').filter(
            id=product_id,
            shopify_profile__user=user,
            deleted_at__isnull=True,
        ).first()
        if product is None:
            raise ValidationError('Product not found for the authenticated user.')
        return product

    @staticmethod
    def _resolve_template(template_id):
        if template_id is not None:
            template = Template.objects.filter(id=template_id, is_active=True).first()
            if template is None:
                raise ValidationError(f'Template with id {template_id} not found')
            return template

        template = Template.objects.filter(
            id=DEFAULT_PRODUCT_CONTENT_TEMPLATE_ID,
            is_active=True,
        ).first()
        if template is not None:
            return template

        template = Template.objects.filter(is_active=True, category='landing_page').order_by('id').first()
        if template is None:
            template = Template.objects.filter(is_active=True).order_by('id').first()
        if template is None:
            raise ValidationError('No active template is available for product content generation.')
        return template

    @staticmethod
    def _populate_template_structure(*, template_structure, product_data, rule_analysis, copy_payload, llm_provider):
        structure = copy.deepcopy(template_structure or {})
        components = structure.get('components')
        if components is None:
            components = structure.get('blocks')
        if components is None:
            components = []
            structure['components'] = components

        hero_image = product_data.get('featured_image_url') or ''
        product_images = [hero_image] + [
            image_url
            for image_url in product_data.get('images') or []
            if image_url and image_url != hero_image
        ]
        gallery_items = rule_analysis.get('gallery_items') or []
        variant_items = rule_analysis.get('variant_items') or []
        missing_placeholders = []
        applied_flags = {
            'gallery': False,
            'urgency': False,
            'bundle': False,
            'price': False,
            'cta': False,
        }

        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue

            props = component.get('props')
            if props is None:
                props = {}
                component['props'] = props
            elif not isinstance(props, dict):
                continue

            block_type = (component.get('type') or '').lower()
            block_id = (component.get('id') or f'component_{index}').lower()
            descriptor = f'{block_id} {block_type}'

            if block_type in ('image', 'image-hero') or 'hero-image' in descriptor:
                ProductContentGenerationService._set_image_props(props, hero_image)

            if any(keyword in descriptor for keyword in ('gallery', 'carousel', 'media-grid')):
                ProductContentGenerationService._set_list_props(props, gallery_items, ['images', 'items', 'slides'])
                applied_flags['gallery'] = True
                continue

            if any(keyword in descriptor for keyword in ('urgency', 'inventory', 'stock', 'scarcity')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.urgency_message or rule_analysis.get('urgency_message') or '',
                    ['text', 'content', 'description', 'subtitle'],
                )
                props['visible'] = bool(rule_analysis.get('blocks', {}).get('show_urgency'))
                applied_flags['urgency'] = True
                continue

            if any(keyword in descriptor for keyword in ('bundle', 'variant', 'option')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.bundle_headline or 'Choose your preferred option',
                    ['title', 'headline', 'heading', 'text'],
                )
                ProductContentGenerationService._set_list_props(props, variant_items, ['items', 'variants', 'options'])
                props['visible'] = bool(rule_analysis.get('blocks', {}).get('show_bundle'))
                applied_flags['bundle'] = True
                continue

            if 'price' in descriptor:
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.price_caption or rule_analysis.get('price_label') or '',
                    ['text', 'price', 'content', 'label'],
                )
                applied_flags['price'] = True
                continue

            if block_type == 'cta' or any(keyword in descriptor for keyword in ('cta', 'button', 'buy', 'shop')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.cta_label or 'Shop now',
                    ['label', 'text', 'title'],
                )
                ProductContentGenerationService._set_url_props(
                    props,
                    product_data.get('product_url') or '',
                )
                applied_flags['cta'] = True
                continue

            if any(keyword in descriptor for keyword in ('subtitle', 'subheadline', 'tagline')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.hero_subtitle or copy_payload.tag_line or product_data.get('seo_description') or '',
                    ['subtitle', 'subheading', 'text', 'content'],
                )
                continue

            if any(keyword in descriptor for keyword in ('benefit', 'feature')):
                ProductContentGenerationService._set_list_props(
                    props,
                    copy_payload.benefit_bullets,
                    ['items', 'benefits', 'bullets'],
                )
                continue

            if any(keyword in descriptor for keyword in ('description', 'body', 'copy', 'details')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.pain_point or product_data.get('description_text') or '',
                    ['text', 'content', 'description', 'body'],
                )
                continue

            if any(keyword in descriptor for keyword in ('title', 'headline', 'hero')):
                ProductContentGenerationService._set_text_props(
                    props,
                    copy_payload.hero_title or product_data.get('title') or '',
                    ['title', 'headline', 'heading', 'text'],
                )

        for placeholder, applied in applied_flags.items():
            if not applied and rule_analysis.get('blocks', {}).get(f'show_{placeholder}'):
                missing_placeholders.append(placeholder)

        structure['generation_metadata'] = {
            'llm_provider': llm_provider,
            'missing_placeholders': missing_placeholders,
            'product_id': product_data.get('id'),
            'rules': rule_analysis,
        }
        return structure

    @staticmethod
    def _set_text_props(props, value, keys):
        if not value:
            return

        for key in keys:
            if key in props:
                props[key] = value
                return

        props[keys[0]] = value

    @staticmethod
    def _set_list_props(props, items, keys):
        if not items:
            return

        for key in keys:
            if key in props:
                props[key] = items
                return

        props[keys[0]] = items

    @staticmethod
    def _set_url_props(props, value):
        if not value:
            return

        for key in ('url', 'href', 'targetUrl'):
            if key in props:
                props[key] = value
                return

        props['url'] = value

    @staticmethod
    def _set_image_props(props, value):
        if not value:
            return

        for key in ('fallbackImage', 'imageUrl', 'src', 'url'):
            if key in props:
                props[key] = value
                return

        props['src'] = value

    @staticmethod
    def _coerce_decimal(value):
        if value in (None, ''):
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None