"""Capture standard save/save_base/delete writers, with default-off fast paths."""
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.finance.models import FinancialCommandReceipt, FundingSource
from . import reference_publication as publication


@receiver(pre_save, sender=FundingSource, weak=False, dispatch_uid="financial_reference_source_before_v1")
def source_before(sender, instance, using, raw=False, **kwargs):
    publication.before_source(instance, using, raw)


@receiver(post_save, sender=FundingSource, weak=False, dispatch_uid="financial_reference_source_after_v1")
def source_after(sender, instance, using, created, **kwargs):
    publication.after_source(instance, using, created)


@receiver(pre_delete, sender=FundingSource, weak=False, dispatch_uid="financial_reference_source_delete_v1")
def source_delete(sender, instance, using, **kwargs):
    publication.before_source(instance, using)


@receiver(pre_save, sender=FinancialCommandReceipt, weak=False, dispatch_uid="financial_reference_invoice_before_v1")
def invoice_before(sender, instance, using, raw=False, **kwargs):
    publication.before_invoice(instance, using, raw)


@receiver(post_save, sender=FinancialCommandReceipt, weak=False, dispatch_uid="financial_reference_invoice_after_v1")
def invoice_after(sender, instance, using, **kwargs):
    publication.after_invoice(instance, using)
