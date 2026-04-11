from apps.content.models import Template, Content
from django.core.exceptions import ValidationError



class ContentService:
    @staticmethod
    def create_content(user, template_id, structure):
        """Create content from template"""
        ContentService._validate_template_exists(template_id)
        ContentService._validate_structure(structure)
        
        content = Content.objects.create(
            user=user,
            template_id=template_id,
            structure=structure
        )
        
        return content
    
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

class TemplateService:
    """Admin service for managing templates."""
    ALLOWED_COMPONENTS = ['hero', 'cta', 'carousel', 'form', 'image', 'slider', 'picker']
    ALLOWED_CATEGORIES = ['landing_page', 'form', 'ecommerce']
    
    
    @staticmethod
    def create_template(name, description, category, structure, thumbnail_url=None):
        """Create a new template with validation"""
        # Call validation static methods
        TemplateService._validate_name(name)
        TemplateService._validate_category(category)
        TemplateService._validate_structure(structure)
        
        # Create if all validations passed
        template = Template.objects.create(
            name=name,
            description=description,
            category=category,
            structure=structure,
            thumbnail_url=thumbnail_url,
            is_active=True
        )
        return template

    @staticmethod
    def _validate_name(name):
        """Validate template name"""
        if not name or len(name) < 3:
            raise ValidationError("Template name must be at least 3 characters")
        
        if Template.objects.filter(name=name).exists():
            raise ValidationError(f"Template with name '{name}' already exists")
    
    @staticmethod
    def _validate_category(category):
        """Validate category is allowed"""
        if category not in TemplateService.ALLOWED_CATEGORIES:
            raise ValidationError(
                f"Invalid category. Allowed: {', '.join(TemplateService.ALLOWED_CATEGORIES)}"
            )
    
    @staticmethod
    def _validate_structure(structure):
        """Validate template structure"""
        if not isinstance(structure, dict):
            raise ValidationError("Structure must be a JSON object")
        
        if 'version' not in structure:
            raise ValidationError("Structure must have a 'version' field")
        
        components = structure.get('components', [])
        if not isinstance(components, list):
            raise ValidationError("Structure 'components' must be a list")
        
        if len(components) == 0:
            raise ValidationError("Template must have at least one component")
        
        # Validate each component
        for i, component in enumerate(components):
            TemplateService._validate_component(component, i)

    @staticmethod
    def _validate_component(component, index):
        """Validate individual component"""
        if not isinstance(component, dict):
            raise ValidationError(f"Component {index} must be an object")
        
        component_type = component.get('type')
        if not component_type:
            raise ValidationError(f"Component {index} missing 'type' field")
        
        if component_type not in TemplateService.ALLOWED_COMPONENTS:
            raise ValidationError(
                f"Component {index}: Invalid type '{component_type}'. "
                f"Allowed: {', '.join(TemplateService.ALLOWED_COMPONENTS)}"
            )
        
        if 'props' not in component:
            raise ValidationError(f"Component {index} missing 'props' field")
