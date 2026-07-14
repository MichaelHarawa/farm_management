"""
global url config
"""
from django.contrib import admin
from django.urls import path,include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import api_index, health

urlpatterns = [
    path("", api_index, name="api-index"),
    path("health/", health, name="health"),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/poultry-management/", include("apps.poultry.urls")),
    path("api/v1/auth/",include("apps.accounts.urls"),),
    path("admin/", admin.site.urls),
]