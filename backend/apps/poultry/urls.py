from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BatchViewset

router = DefaultRouter(trailing_slash=False)
router.register("", BatchViewset, basename="batch")

app_name = "poultry"

urlpatterns = [
    path("", include(router.urls)),
]

