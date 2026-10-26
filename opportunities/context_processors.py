from django.conf import settings
from .models import Employer

def pilot_notice(request):
    return {"demo_preview": settings.DEBUG and Employer.objects.filter(is_demo=True).exists()}
