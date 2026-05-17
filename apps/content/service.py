import copy
import logging
import os
import uuid
import hashlib
import json
from decimal import Decimal, InvalidOperation

from apps.content.models import Template, Content
from apps.content.llm import ProductCopyPayload, build_llm_client
from apps.content.rules import ProductRuleEngine
from apps.shopify.models import ShopifyProduct as Sh
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.core.files.storage import default_storage
from django.utils.html import strip_tags


logger = logging.getLogger(__name__)

DEFAULT_PRODUCT_CONTENT_TEMPLATE_ID = 1


class ContentService:
    @staticmethod
    def create_content(user, template_id, structure, files=None):
        upload_payload = ContentService.upload_content(user, template_id, structure, files=files)

        # Prefer idempotent lookup using generation_metadata.idempotency_key
        # when present. Use DB-backed uniqueness to avoid race conditions.
        existing = None
        try:
            struct = upload_payload.get('structure') or {}
            gen_meta = struct.get('generation_metadata') if isinstance(struct, dict) else None
            idempotency_key = gen_meta.get('idempotency_key') if isinstance(gen_meta, dict) else None
        except Exception:
            idempotency_key = None

        if idempotency_key:
            try:
                # Use atomic get_or_create to prevent duplicates under concurrency.
                with transaction.atomic():
                    content, created = Content.objects.get_or_create(
                        idempotency_key=idempotency_key,
                        defaults={
                            'user': user,
                            'template': upload_payload['template'],
                            'structure': upload_payload['structure'],
                        },
                    )
                    return content
            except IntegrityError:
                # Another process created it concurrently — fetch it now.
                existing = Content.objects.filter(idempotency_key=idempotency_key).first()

        if existing is None:
            existing = Content.objects.filter(user=user, structure=upload_payload['structure']).first()
        if existing is not None:
            return existing

        content_kwargs = {
            'user': user,
            'template': upload_payload['template'],
            'structure': upload_payload['structure'],
        }
        if idempotency_key:
            content_kwargs['idempotency_key'] = idempotency_key

        content = Content.objects.create(**content_kwargs)

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
    def delete_content(content, user=None):
        """Delete a Content record, enforcing ownership when a user is provided."""
        if user is not None and content.user != user:
            raise ValidationError("You don't have permission to delete this content.")

        content.delete()

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

        # Compute an idempotency key from the product, template and the LLM copy
        # payload so repeated generation calls produce the same key and can be
        # deduplicated even when injected component ids differ.
        try:
            copy_dict = copy_payload.model_dump() if hasattr(copy_payload, 'model_dump') else dict(copy_payload or {})
        except Exception:
            copy_dict = {}

        hash_input = {
            'user_id': getattr(user, 'id', None),
            'product_id': normalized_data.get('id'),
            'template_id': template.id,
            'llm_provider': llm_client.provider_name,
            'copy': {
                'hero_title': copy_dict.get('hero_title'),
                'hero_subtitle': copy_dict.get('hero_subtitle'),
                'pain_point': copy_dict.get('pain_point'),
                'benefit_bullets': copy_dict.get('benefit_bullets'),
                'cta_label': copy_dict.get('cta_label'),
                'urgency_message': copy_dict.get('urgency_message'),
                'bundle_headline': copy_dict.get('bundle_headline'),
                'bundle_items': copy_dict.get('bundle_items'),
                'price_caption': copy_dict.get('price_caption'),
                'tag_line': copy_dict.get('tag_line'),
            }
        }

        # Allow non-JSON-native values (UUID, Decimal, etc.) to be
        # deterministically stringified when computing the hash.
        idempotency_key = hashlib.sha256(
            json.dumps(hash_input, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
        ).hexdigest()
        generated_structure.setdefault('generation_metadata', {})['idempotency_key'] = idempotency_key
        logger.debug('Generated structure idempotency_key set')
        content = None
        # if persist:
        #     content = ContentService.create_content(
        #         user=user,
        #         template_id=template.id,
        #         structure=generated_structure,
        #     )

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
        
        gallery_items = rule_analysis.get('gallery_items') or []
        variant_items = rule_analysis.get('variant_items') or []
        missing_placeholders = []

        # Track which placeholders already exist in the template copy
        applied_flags = {
            'gallery': False,
            'urgency': False,
            'bundle': False,
            'price': False,
            'cta': False,
            'title': False,
            'subtitle': False,
            'benefits': False,
            'description': False,
            'tagline': False,
        }

        # Quick scan to mark which placeholders are already present
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue

            block_type = (component.get('type') or '').lower()
            block_id = (component.get('id') or f'component_{index}').lower()
            descriptor = f'{block_id} {block_type}'

            if any(keyword in descriptor for keyword in ('gallery', 'carousel', 'media-grid')):
                applied_flags['gallery'] = True
            if any(keyword in descriptor for keyword in ('urgency', 'inventory', 'stock', 'scarcity')):
                applied_flags['urgency'] = True
            if any(keyword in descriptor for keyword in ('bundle', 'variant', 'option')):
                applied_flags['bundle'] = True
            if 'price' in descriptor:
                applied_flags['price'] = True
            if block_type == 'cta' or any(keyword in descriptor for keyword in ('cta', 'button', 'buy', 'shop')):
                applied_flags['cta'] = True
            if any(keyword in descriptor for keyword in ('title', 'headline', 'hero')):
                applied_flags['title'] = True
            if any(keyword in descriptor for keyword in ('subtitle', 'subheadline', 'tagline')):
                applied_flags['subtitle'] = True
            if any(keyword in descriptor for keyword in ('benefit', 'feature', 'list', 'bullets')):
                applied_flags['benefits'] = True
            if any(keyword in descriptor for keyword in ('description', 'body', 'details', 'copy')):
                applied_flags['description'] = True
            if any(keyword in descriptor for keyword in ('tag', 'tagline')):
                applied_flags['tagline'] = True

        # Normalize the pydantic payload into a dict
        if hasattr(copy_payload, 'model_dump'):
            payload_dict = copy_payload.model_dump()
        else:
            payload_dict = dict(copy_payload or {})

        def _add_component(type_, props, id_prefix):
            print('ADDING',type_,props)
            comp_id = f'injected_{id_prefix}_{uuid.uuid4().hex[:8]}'
            components.append({'id': comp_id, 'type': type_, 'props': props})
            return comp_id

        hero_title = (payload_dict.get('hero_title') or '').strip()
        hero_subtitle = (payload_dict.get('hero_subtitle') or payload_dict.get('tag_line') or '').strip()
        if (hero_title or hero_subtitle) and not (applied_flags['title'] or applied_flags['subtitle']):
            props = {}
            if hero_title:
                props['title'] = hero_title
            if hero_subtitle:
                props['subtitle'] = hero_subtitle
            if hero_image:
                props['fallbackImage'] = hero_image
            props['visible'] = True
            _add_component('hero', props, 'hero')

        # Inject description / pain point
        pain_point = (payload_dict.get('pain_point') or '').strip()
        if pain_point and not applied_flags['description']:
            _add_component('text-desc', {'text': pain_point, 'visible': True}, 'description')

        # Inject benefits list
        benefits = payload_dict.get('benefit_bullets') or []
        if benefits and not applied_flags['benefits']:
            _add_component('list', {'items': benefits, 'visible': True}, 'benefits')

        # Inject CTA
        cta_label = (payload_dict.get('cta_label') or '').strip()
        product_url = product_data.get('product_url') or ''
        if (cta_label or product_url) and not applied_flags['cta']:
            props = {}
            if cta_label:
                props['label'] = cta_label
            if product_url:
                props['url'] = product_url
            props['visible'] = True
            _add_component('cta', props, 'cta')

        # Inject urgency
        urgency_text = (payload_dict.get('urgency_message') or rule_analysis.get('urgency_message') or '').strip()
        if urgency_text and not applied_flags['urgency']:
            _add_component('urgency_text', {'text': urgency_text, 'visible': True}, 'urgency')

        # Inject bundle / variant options
        bundle_items = payload_dict.get('bundle_items') or []
        bundle_headline = payload_dict.get('bundle_headline')
        if not bundle_items and variant_items:
            bundle_items = [item.get('title') for item in variant_items if item.get('title')]
        if (bundle_items or bundle_headline) and not applied_flags['bundle']:
            props = {}
            if bundle_headline:
                props['heading'] = bundle_headline
            if bundle_items:
                props['items'] = bundle_items
            props['visible'] = True
            _add_component('product-bundle', props, 'bundle')


        price_caption = (payload_dict.get('price_caption') or '').strip()
        if price_caption and not applied_flags['price']:
            _add_component('price', {'price': price_caption, 'visible': True}, 'price')

        # Inject tagline if provided
        tag_line = (payload_dict.get('tag_line') or '').strip()
        if tag_line and not (applied_flags['subtitle'] or applied_flags['tagline']):
            _add_component('text-tag', {'text': tag_line, 'visible': True}, 'tagline')

        # Inject gallery if rule provided images
        if gallery_items and not applied_flags['gallery']:
            _add_component('gallery', {'images': gallery_items, 'items': gallery_items, 'visible': True}, 'gallery')

        # Now populate all components (including injected ones) using existing population logic
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
                if hero_image:
                    props['visible'] = True

            if any(keyword in descriptor for keyword in ('gallery', 'carousel', 'media-grid')):
                ProductContentGenerationService._set_list_props(props, gallery_items, ['images', 'items', 'slides'])
                if gallery_items:
                    props['visible'] = True
                applied_flags['gallery'] = True
                continue

            if any(keyword in descriptor for keyword in ('urgency', 'inventory', 'stock', 'scarcity')):
                urgency_text_local = payload_dict.get('urgency_message') or rule_analysis.get('urgency_message') or ''
                ProductContentGenerationService._set_text_props(
                    props,
                    urgency_text_local,
                    ['text', 'content', 'description', 'subtitle'],
                )
                props['visible'] = bool(rule_analysis.get('blocks', {}).get('show_urgency')) or bool(urgency_text_local)
                applied_flags['urgency'] = True
                continue

            if any(keyword in descriptor for keyword in ('bundle', 'variant', 'option')):
                bundle_text = payload_dict.get('bundle_headline') or 'Choose your preferred option'
                ProductContentGenerationService._set_text_props(
                    props,
                    bundle_text,
                    ['title', 'headline', 'heading', 'text'],
                )
                ProductContentGenerationService._set_list_props(props, variant_items or payload_dict.get('bundle_items') or [], ['items', 'variants', 'options'])
                props['visible'] = bool(rule_analysis.get('blocks', {}).get('show_bundle')) or bool(variant_items or payload_dict.get('bundle_items'))
                applied_flags['bundle'] = True
                continue

            if 'price' in descriptor:
                price_text = payload_dict.get('price_caption') or rule_analysis.get('price_label') or ''
                ProductContentGenerationService._set_text_props(
                    props,
                    price_text,
                    ['text', 'price', 'content', 'label'],
                )
                if price_text:
                    props['visible'] = True
                applied_flags['price'] = True
                continue

            if block_type == 'cta' or any(keyword in descriptor for keyword in ('cta', 'button', 'buy', 'shop')):
                cta_text = payload_dict.get('cta_label') or 'Shop now'
                ProductContentGenerationService._set_text_props(
                    props,
                    cta_text,
                    ['label', 'text', 'title'],
                )
                ProductContentGenerationService._set_url_props(
                    props,
                    product_data.get('product_url') or '',
                )
                if cta_text or product_data.get('product_url'):
                    props['visible'] = True
                applied_flags['cta'] = True
                continue

            if any(keyword in descriptor for keyword in ('subtitle', 'subheadline', 'tagline')):
                subtitle_text = payload_dict.get('hero_subtitle') or payload_dict.get('tag_line') or product_data.get('seo_description') or ''
                ProductContentGenerationService._set_text_props(
                    props,
                    subtitle_text,
                    ['subtitle', 'subheading', 'text', 'content'],
                )
                if subtitle_text:
                    props['visible'] = True
                continue

            if any(keyword in descriptor for keyword in ('benefit', 'feature')):
                benefits_local = payload_dict.get('benefit_bullets') or []
                ProductContentGenerationService._set_list_props(
                    props,
                    benefits_local,
                    ['items', 'benefits', 'bullets'],
                )
                if benefits_local:
                    props['visible'] = True
                continue

            if any(keyword in descriptor for keyword in ('description', 'body', 'copy', 'details')):
                desc_text = payload_dict.get('pain_point') or product_data.get('description_text') or ''
                ProductContentGenerationService._set_text_props(
                    props,
                    desc_text,
                    ['text', 'content', 'description', 'body'],
                )
                if desc_text:
                    props['visible'] = True
                continue

            if any(keyword in descriptor for keyword in ('title', 'headline', 'hero')):
                title_text = payload_dict.get('hero_title') or product_data.get('title') or ''
                ProductContentGenerationService._set_text_props(
                    props,
                    title_text,
                    ['title', 'headline', 'heading', 'text'],
                )
                if title_text:
                    props['visible'] = True

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