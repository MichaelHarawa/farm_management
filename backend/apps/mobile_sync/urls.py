from django.urls import path
from .views import (DeviceView, RevokeDeviceView, CapabilitiesView, BootstrapView,
                    BootstrapPageView, ChangesView, PushView, OperationView, OnlinePoultryView)
from .financial_views import (FinancialReadCapabilitiesView, SupplierPaymentStatusView,
                             SupplierPaymentSummaryView)
from .reference_views import (ReferenceCapabilitiesView, FundingReferenceCatalogView,
                             InvoiceReferenceCatalogView, InvoiceReferenceDetailView)
from .storage_views import FinancialStorageGrantView

app_name = "mobile_sync"
urlpatterns = [
    path("finance/storage/grant", FinancialStorageGrantView.as_view(), name="finance-storage-grant"),
    path("finance/references/capabilities", ReferenceCapabilitiesView.as_view(), name="finance-reference-capabilities"),
    path("finance/references/funding", FundingReferenceCatalogView.as_view(), name="finance-reference-funding"),
    path("finance/references/invoices", InvoiceReferenceCatalogView.as_view(), name="finance-reference-invoices"),
    path("finance/references/invoices/<uuid:invoice_id>", InvoiceReferenceDetailView.as_view(), name="finance-reference-invoice-detail"),
    path("finance/capabilities", FinancialReadCapabilitiesView.as_view(), name="finance-read-capabilities"),
    path("finance/supplier-payments/<uuid:operation_id>/status", SupplierPaymentStatusView.as_view(), name="supplier-payment-status"),
    path("finance/supplier-payments/<uuid:operation_id>/summary", SupplierPaymentSummaryView.as_view(), name="supplier-payment-summary"),
    path("poultry-online", OnlinePoultryView.as_view(), name="poultry-online"),
    path("devices", DeviceView.as_view(), name="devices"),
    path("devices/<uuid:device_id>/revoke", RevokeDeviceView.as_view(), name="revoke"),
    path("capabilities", CapabilitiesView.as_view(), name="capabilities"),
    path("bootstrap", BootstrapView.as_view(), name="bootstrap"),
    path("bootstrap/<uuid:snapshot_id>/pages", BootstrapPageView.as_view(), name="pages"),
    path("changes", ChangesView.as_view(), name="changes"),
    path("push", PushView.as_view(), name="push"),
    path("operations/<uuid:operation_id>", OperationView.as_view(), name="operation"),
]
