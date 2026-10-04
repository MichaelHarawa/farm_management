from __future__ import annotations

from datetime import timedelta

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from apps.mobile_sync.policy import PoultryPermission, SUPERVISORS, permits
from apps.mobile_sync.projections import project, public_payload
from rest_framework import serializers
from rest_framework.response import Response
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.finance.models import AccountingPeriod, PeriodStatus
from apps.finance.permissions import FinancePermission
from apps.finance.services.expenditures import (
    batch_cost_records,
    create_batch_cost_transaction,
)
from apps.poultry.services.batch_lifecycle import (
    assert_batch_accepts_cost,
    assert_batch_in_production,
    create_mortality_with_lifecycle,
    create_sale_with_lifecycle,
    recalculate_batch_status,
)
from apps.poultry.services.feed_metrics import (
    create_flock_adjustment,
    feed_summary,
    recalculate_feed_event_populations,
    record_feed_usage,
    sell_by_recommendation,
)
from apps.poultry.services.growth import (
    compute_growth_series,
    get_broiler_strain_for_batch,
    latest_growth_status,
)
from apps.poultry.services.dashboard import poultry_dashboard
from apps.poultry.services.operations import (register_batch, mark_delivered as mark_batch_delivered,
    confirm_delivery as confirm_batch_delivery, record_treatment, record_weight)

from .models import(
    Batch,
    BatchStatus,
    BatchWeightSample,
    InputCosts,
    Sales,
    Mortality,
    FeedUsage,
    FlockAdjustment,
    DrugsVaccination,
)

from .serializers import(
    BatchDeliverySerializer,
    BatchForecastAssumptionSerializer,
    BatchSerializer,
    BatchStatusTransitionSerializer,
    BatchWeightSampleSerializer,
    InputCostsSerializer,
    SalesSerializer,
    MortalitySerializer,
    FeedUsageSerializer,
    FlockAdjustmentSerializer,
    DrugsVaccinationSerializer,
)

class OperationalBatchSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return public_payload("poultry.batch", project(instance, None))


def operational_write(service, **kwargs):
    try:
        return service(**kwargs)
    except DjangoValidationError as error:
        raise ValidationError(getattr(error, "message_dict", None) or {"detail": error.messages}) from error
    except ValueError as error:
        raise ValidationError({"batch": str(error)}) from error


class BatchViewset(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BatchSerializer
    queryset = Batch.objects.select_related("created_by")
    permission_classes = (PoultryPermission,)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        if not permits(request.user, SUPERVISORS | {"stake_holder"}):
            return Response({"server_time": timezone.now(), "results": [project(batch, None) for batch in self.get_queryset()]})
        return Response(poultry_dashboard(request.query_params))

    def perform_create(self, serializer):
        serializer.instance = operational_write(register_batch, created_by=self.request.user, **serializer.validated_data)

    def save_with_current_user(self, serializer, **kwargs):
        return serializer.save(
            created_by=self.request.user,
            **kwargs,
        )

    def get_serializer_class(self):
        if self.action == "confirm_delivery":
            return BatchDeliverySerializer
        elif self.action == "forecast_assumptions":
            return BatchForecastAssumptionSerializer
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
        elif self.action == "flock_adjustments":
            return FlockAdjustmentSerializer
        elif self.action == "drugs_vaccine":
            return DrugsVaccinationSerializer
        elif self.action == "weight_samples":
            return BatchWeightSampleSerializer
        if self.request.method == "GET" and not permits(self.request.user, SUPERVISORS | {"stake_holder"}):
            return OperationalBatchSerializer
        return BatchSerializer

    @action(
        detail=True,
        methods=["patch"],
        url_path="forecast-assumptions",
        permission_classes=[FinancePermission],
    )
    def forecast_assumptions(self, request, pk=None):
        batch = self.get_object()
        serializer = self.get_serializer(batch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

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

        poultry_batch = operational_write(mark_batch_delivered, batch_id=poultry_batch.pk)

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
        poultry_batch = operational_write(confirm_batch_delivery, batch_id=poultry_batch.pk, **data)

        return Response(
            BatchSerializer(poultry_batch, context=self.get_serializer_context()).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="input_costs")
    def input_costs(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            return Response(batch_cost_records(poultry_batch), status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purchase_date = serializer.validated_data["purchase_date"].date()
        correction_period_is_open = AccountingPeriod.objects.filter(
            period_start__lte=purchase_date,
            period_end__gte=purchase_date,
            status=PeriodStatus.OPEN,
        ).exists()
        try:
            assert_batch_accepts_cost(
                poultry_batch,
                allow_closed_cost_correction=correction_period_is_open,
            )
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        input_cost = create_batch_cost_transaction(
            batch=poultry_batch,
            data=dict(serializer.validated_data),
            user=request.user,
        )

        return Response(
            self.get_serializer(input_cost).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="feed_input_costs")
    def feed_input_costs(self, request, pk=None):
        poultry_batch = self.get_object()
        input_costs = [
            row for row in batch_cost_records(poultry_batch)
            if "feed" in row["category"].lower()
        ]
        return Response(input_costs, status=status.HTTP_200_OK)


    @action(detail=True, methods=["get", "post"], url_path="sales")
    def sales(self, request, pk=None):
        poultry_batch = self.get_object()

        if request.method == "GET":
            sales = poultry_batch.sales_row.prefetch_related("selling_costs").order_by("-created_at")
            serializer = self.get_serializer(sales, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sale = operational_write(create_sale_with_lifecycle,
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
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
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

        try:
            feed_usage = record_feed_usage(
                batch_id=poultry_batch.pk,
                created_by=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        except ValueError as error:
            raise ValidationError({"batch": str(error)}) from error

        return Response(
            self.get_serializer(feed_usage).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="feed-metrics")
    def feed_metrics(self, request, pk=None):
        return Response(feed_summary(self.get_object()))

    @action(detail=True, methods=["get"], url_path="sell-by-recommendation")
    def sell_by_guidance(self, request, pk=None):
        return Response(sell_by_recommendation(self.get_object()))

    @action(detail=True, methods=["post"], url_path="recalculate-feed-metrics")
    def recalculate_feed_metrics(self, request, pk=None):
        batch = self.get_object()
        records = recalculate_feed_event_populations(batch)
        return Response(
            {
                "records_recalculated": len(records),
                "summary": feed_summary(batch),
            }
        )

    @action(detail=True, methods=["get", "post"], url_path="flock-adjustments")
    def flock_adjustments(self, request, pk=None):
        batch = self.get_object()
        if request.method == "GET":
            return Response(
                self.get_serializer(batch.flock_adjustments.all(), many=True).data
            )
        try:
            assert_batch_in_production(batch)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = operational_write(create_flock_adjustment,
            batch_id=batch.pk,
            approved_by=request.user,
            **serializer.validated_data,
        )
        return Response(
            self.get_serializer(adjustment).data,
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

        vaccination = operational_write(record_treatment, batch_id=poultry_batch.pk,
            created_by=request.user, **serializer.validated_data)

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

        sample = operational_write(record_weight, batch_id=poultry_batch.pk,
            created_by=request.user, **serializer.validated_data)

        return Response(
            self.get_serializer(sample).data,
            status=status.HTTP_201_CREATED,
        )


