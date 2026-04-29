from django.contrib import admin
from .models import User, ShopifyProfile, Wallet, CreditLedger,AuthProvider, EmailVerification

admin.site.register(User)
admin.site.register(ShopifyProfile)
admin.site.register(AuthProvider)
admin.site.register(EmailVerification)
admin.site.register(Wallet)
admin.site.register(CreditLedger)
