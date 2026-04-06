from django.contrib import admin
from .models import User, ShopifyProfile, AuthProvider, EmailVerification

admin.site.register(User)
admin.site.register(ShopifyProfile)
admin.site.register(AuthProvider)
admin.site.register(EmailVerification)
