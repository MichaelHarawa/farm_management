from django.contrib import admin

from .models import (
    Batch,
    DrugsVaccination,
    FeedUsage,
    InputCosts,
    Mortality,
    Sales,
)


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "bird_type", "quantity", "status", "entry_date")
    list_filter = ("status", "bird_type", "source")
    search_fields = ("batch_id",)


@admin.register(InputCosts)
class InputCostsAdmin(admin.ModelAdmin):
    list_display = ("batch", "item", "category", "direct_input_total", "purchase_date")
    list_filter = ("category", "purchase_date")
    search_fields = ("batch__batch_id", "item", "category")
    autocomplete_fields = ("batch", "created_by")


@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_display = ("sale_id", "batch", "product_type", "sale_total", "balance", "payment_status")
    list_filter = ("product_type", "payment_status", "sale_date")
    search_fields = ("sale_id", "batch__batch_id", "buyer_name")
    autocomplete_fields = ("batch", "created_by")


@admin.register(Mortality)
class MortalityAdmin(admin.ModelAdmin):
    list_display = ("batch", "quantity_dead", "mortality_date", "suspected_cause")
    list_filter = ("mortality_date",)
    search_fields = ("batch__batch_id", "suspected_cause")
    autocomplete_fields = ("batch", "created_by")


@admin.register(FeedUsage)
class FeedUsageAdmin(admin.ModelAdmin):
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
