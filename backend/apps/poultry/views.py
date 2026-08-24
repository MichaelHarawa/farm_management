from __future__ import annotations

from datetime import timedelta

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone

from apps.finance.models import AccountingPeriod, PeriodStatus
from apps.poultry.services.batch_lifecycle import (
    assert_batch_in_production,
    create_mortality_with_lifecycle,
    create_sale_with_lifecycle,
    recalculate_batch_status,
)
from apps.poultry.services.growth import (
    compute_growth_series,
    get_broiler_strain_for_batch,
    latest_growth_status,
)

from .models import(
    Batch,
    BatchStatus,
    BatchWeightSample,
    InputCosts,
    Sales,
    Mortality,
    FeedUsage,
    DrugsVaccination,
)

from .serializers import(
    BatchDeliverySerializer,
    BatchSerializer,
    BatchStatusTransitionSerializer,
    BatchWeightSampleSerializer,
    InputCostsSerializer,
    SalesSerializer,
    MortalitySerializer,
    FeedUsageSerializer,
    DrugsVaccinationSerializer,
)

class BatchViewset(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    queryset = Batch.objects.select_related("created_by")
    permission_classes = (IsAuthenticated,)

    def perform_create(self, serializer):
        batch = serializer.save(created_by=self.request.user)
        recalculate_batch_status(batch)

    def save_with_current_user(self, serializer, **kwargs):
        return serializer.save(
            created_by=self.request.user,
            **kwargs,
        )

    def get_serializer_class(self):
        if self.action == "confirm_delivery":
            return BatchDeliverySerializer
        elif self.action == "mark_delivered":
            return BatchStatusTransitionSerializer
        elif self.action in {"input_costs", "feed_input_costs"}:
            return InputCostsSerializer
        elif self.action == "sales":
            return SalesSerializer
        elif self.action == "mortality":
            return MortalitySerializer
        elif self.action == "feed_usage":
            return FeedUsageSerializer
        elif self.action == "drugs_vaccine":
            return DrugsVaccinationSerializer
        elif self.action == "weight_samples":
            return BatchWeightSampleSerializer
        return BatchSerializer

    @action(detail=True, methods=["post"], url_path="mark-delivered")
    def mark_delivered(self, request, pk=None):
        poultry_batch = self.get_object()

        if poultry_batch.status == BatchStatus.CLOSED:
            raise ValidationError({"status": "Closed batches cannot be changed."})

        if poultry_batch.status != BatchStatus.BOOKED:
            raise ValidationError(
                {
                    "status": (
                        "Only booked batches can be marked delivered before "
                        "batch details are added."
                    )
                }
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        poultry_batch.status = BatchStatus.DELIVERED
        poultry_batch.delivery_confirmed_at = timezone.now()
        poultry_batch.save(update_fields=["status", "delivery_confirmed_at", "updated_at"])

        return Response(
            BatchSerializer(poultry_batch, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="confirm-delivery")
    def confirm_delivery(self, request, pk=None):
        poultry_batch = self.get_object()

        if poultry_batch.status == BatchStatus.CLOSED:
            raise ValidationError({"status": "Closed batches cannot be changed."})

        if poultry_batch.status != BatchStatus.DELIVERED:
            raise ValidationError(
                {
                    "status": (
                        "Mark the booked chicks as delivered before adding "
                        "batch details."
                    )
                }
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entry_date = data["entry_date"]

        poultry_batch.entry_date = entry_date
        poultry_batch.expected_maturity_date = data.get(
            "expected_maturity_date",
            entry_date + timedelta(days=46),
        )
        poultry_batch.quantity = data.get("quantity", poultry_batch.quantity)
        poultry_batch.delivery_confirmed_at = (
            poultry_batch.delivery_confirmed_at or timezone.now()
        )
        poultry_batch.status = BatchStatus.PLANNED
        poultry_batch.save(
            update_fields=[
                "entry_date",
                "expected_maturity_date",
                "quantity",
                "delivery_confirmed_at",
                "status",
                "updated_at",
            ]
        )
        recalculate_batch_status(poultry_batch)

        return Response(
            BatchSerializer(poultry_batch, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="input_costs")
    def input_costs(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            input_costs = poultry_batch.input_costs.all().order_by(
                "-purchase_date",
                "-created_at",
            )
            serializer = self.get_serializer(input_costs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purchase_date = serializer.validated_data["purchase_date"].date()
        correction_period_is_open = AccountingPeriod.objects.filter(
            period_start__lte=purchase_date,
            period_end__gte=purchase_date,
            status=PeriodStatus.OPEN,
        ).exists()
        try:
            assert_batch_in_production(
                poultry_batch,
                allow_closed_cost_correction=correction_period_is_open,
            )
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        input_cost = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(input_cost).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="feed_input_costs")
    def feed_input_costs(self, request, pk=None):
        poultry_batch = self.get_object()
        input_costs = poultry_batch.input_costs.filter(
            category__icontains="feed",
        ).order_by(
            "-purchase_date",
            "-created_at",
        )
        serializer = self.get_serializer(input_costs, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


    @action(detail=True, methods=["get", "post"], url_path="sales")
    def sales(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            sales = poultry_batch.sales_row.all().order_by("-created_at")
            serializer = self.get_serializer(sales, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sale = create_sale_with_lifecycle(
                batch_id=poultry_batch.pk,
                created_by=request.user,
                **serializer.validated_data,
            )
        except ValueError as error:
            raise ValidationError({"quantity_sold": str(error)}) from error
        return Response(
            self.get_serializer(sale).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="mortality")
    def mortality(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            mortalities = poultry_batch.mortality_row.all().order_by("-created_at")
            serializer = self.get_serializer(mortalities, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            mortality = create_mortality_with_lifecycle(
                batch_id=poultry_batch.pk,
                created_by=request.user,
                **serializer.validated_data,
            )
        except ValueError as error:
            raise ValidationError({"quantity_dead": str(error)}) from error
        return Response(
            self.get_serializer(mortality).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="feed_usage")
    def feed_usage(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            feed_usages = poultry_batch.feed_usage_row.all().order_by("-created_at")
            serializer = self.get_serializer(feed_usages, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            assert_batch_in_production(poultry_batch)
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feed_usage = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(feed_usage).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="drugs_vaccine")
    def drugs_vaccine(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            vaccinations = poultry_batch.vaccination_row.all().order_by(
                "-vaccination_date",
                "-created_at",
            )
            serializer = self.get_serializer(vaccinations, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            assert_batch_in_production(poultry_batch)
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vaccination = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(vaccination).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="weight_samples")
    def weight_samples(self, request, pk=None):
        """CRUD for live weight samples. GET returns series + latest alert status."""
        poultry_batch = self.get_object()

        if request.method == "GET":
            samples = poultry_batch.weight_samples.all().order_by("sampled_at")
            ser = self.get_serializer(samples, many=True)
            return Response(
                {
                    "samples": ser.data,
                    "latest_status": latest_growth_status(poultry_batch),
                    "strain": get_broiler_strain_for_batch(poultry_batch),
                    "series": compute_growth_series(poultry_batch),
                },
                status=status.HTTP_200_OK,
            )

        # Only allow weight sampling on active production batches
        try:
            assert_batch_in_production(poultry_batch)
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sample = self.save_with_current_user(
            serializer,
            batch=poultry_batch,
        )

        return Response(
            self.get_serializer(sample).data,
            status=status.HTTP_201_CREATED,
        )


