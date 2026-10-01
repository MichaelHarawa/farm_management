from django.contrib import admin
from apps.mobile_sync.writers import capture_enabled

from .models import (
    Batch,
    BatchWeightSample,
    BroilerStrain,
    DrugsVaccination,
    FeedUsage,
    InputCosts,
    Mortality,
    Sales,
    SaleSellingCost,
)


class PublishedReadOnlyAdmin(admin.ModelAdmin):
    """Old generic admin editors bypass dated lifecycle/financial services.

    Once sync capture is active, retain admin viewing but require the authorized
    operational service API for writes. Do not pretend generic admin is safe.
    """
    def has_add_permission(self, request):
        return not capture_enabled() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not capture_enabled() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not capture_enabled() and super().has_delete_permission(request, obj)


@admin.register(Batch)
class BatchAdmin(PublishedReadOnlyAdmin):
    list_display = ("batch_id", "bird_type", "broiler_strain", "quantity", "status", "entry_date")
    list_filter = ("status", "bird_type", "broiler_strain", "source")
    search_fields = ("batch_id",)


@admin.register(InputCosts)
class InputCostsAdmin(admin.ModelAdmin):
    list_display = ("batch", "item", "category", "direct_input_total", "purchase_date")
    list_filter = ("category", "purchase_date")
    search_fields = ("batch__batch_id", "item", "category")
    autocomplete_fields = ("batch", "created_by")


@admin.register(Sales)
class SalesAdmin(PublishedReadOnlyAdmin):
    list_display = ("sale_id", "batch", "product_type", "sale_total", "balance", "payment_status", "receivable_follow_up_name")
    list_filter = ("product_type", "payment_status", "sale_date")
    search_fields = ("sale_id", "batch__batch_id", "buyer_name", "receivable_follow_up_name")
    autocomplete_fields = ("batch", "created_by")


@admin.register(SaleSellingCost)
class SaleSellingCostAdmin(admin.ModelAdmin):
    list_display = ("sale", "category", "amount", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("sale__sale_id", "sale__buyer_name", "notes")
    autocomplete_fields = ("sale", "created_by")


@admin.register(Mortality)
class MortalityAdmin(PublishedReadOnlyAdmin):
    list_display = ("batch", "quantity_dead", "mortality_date", "suspected_cause")
    list_filter = ("mortality_date",)
    search_fields = ("batch__batch_id", "suspected_cause")
    autocomplete_fields = ("batch", "created_by")


@admin.register(FeedUsage)
class FeedUsageAdmin(PublishedReadOnlyAdmin):
    list_display = ("batch", "feed_type", "quantity_given", "feeding_start_date")
    list_filter = ("feed_type", "feed_source")
    search_fields = ("batch__batch_id",)
    autocomplete_fields = ("batch", "created_by")


@admin.register(DrugsVaccination)
class DrugsVaccinationAdmin(admin.ModelAdmin):
    list_display = ("batch", "drug_category", "drug_vaccination_type", "vaccination_date")
    list_filter = ("drug_category", "drug_vaccination_type")
    search_fields = ("batch__batch_id", "other_drug_vaccination")
    autocomplete_fields = ("batch", "created_by")


@admin.register(BatchWeightSample)
class BatchWeightSampleAdmin(admin.ModelAdmin):
    list_display = ("batch", "age_in_days", "average_weight_g", "sample_size", "sampled_at")
    list_filter = ("age_in_days",)
    search_fields = ("batch__batch_id",)
    autocomplete_fields = ("batch", "created_by")
