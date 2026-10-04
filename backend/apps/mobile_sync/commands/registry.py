"""Frozen v1 mortality and opt-in v2 poultry commands; never arbitrary model CRUD."""
from dataclasses import dataclass

from apps.mobile_sync.policy import OPERATORS, SUPERVISORS


def resolve_batch(command, state, *, expected=False):
    from apps.mobile_sync.errors import SyncError
    from apps.mobile_sync.models import SyncEntity
    mapping = SyncEntity.objects.filter(stream=state["stream"], entity_uuid=command["payload"]["batch_uuid"],
                                        entity_type="poultry.batch", deleted=False).first()
    if mapping is None:
        raise SyncError("reference_unavailable", "Batch reference is unavailable.")
    if expected:
        if str(command["entity_uuid"]) != str(mapping.entity_uuid):
            raise SyncError("entity_uuid_conflict", "Lifecycle command must target its batch identity.", 409)
        assert_revision(command, mapping, state)
    return mapping


def assert_revision(command, mapping, state):
    from apps.mobile_sync.errors import SyncError
    revision = command["base_version"]
    if revision is None:
        # A locally-created parent has no server revision yet. Immutable intent
        # explicitly names prerequisite operations, never mutates on retry.
        versions = [entity["revision"] for receipt in state.get("dependencies", [])
            for entity in receipt.result.get("canonical_entities", [])
            if entity["entity_uuid"] == str(mapping.entity_uuid)]
        revision = max(versions, key=int) if versions else None
    if revision != str(mapping.revision):
        raise SyncError("revision_conflict", "Current revision differs; review without overwriting.", 409)


def mortality_record(command, actor, state):
    from apps.poultry.services.batch_lifecycle import create_mortality_with_lifecycle
    mapping = resolve_batch(command, state)
    data = dict(command["payload"])
    data.pop("batch_uuid")
    mortality = create_mortality_with_lifecycle(batch_id=int(mapping.source_pk), created_by=actor, **data)
    state["entity_ids"][("poultry.mortality", str(mortality.pk))] = command["entity_uuid"]
    return mortality, mapping


def append_record(service, entity_type):
    def handler(command, actor, state):
        mapping = resolve_batch(command, state)
        data = {key: value for key, value in command["payload"].items() if key != "batch_uuid"}
        record = service(batch_id=int(mapping.source_pk), created_by=actor, **data)
        state["entity_ids"][(entity_type, str(record.pk))] = command["entity_uuid"]
        return record, mapping
    return handler


def book(command, actor, state):
    from apps.poultry.services.operations import register_batch
    batch = register_batch(created_by=actor, **command["payload"])
    state["entity_ids"][("poultry.batch", str(batch.pk))] = command["entity_uuid"]
    return batch, None


def delivery(command, actor, state):
    from apps.poultry.services.operations import mark_delivered, confirm_delivery
    mapping = resolve_batch(command, state, expected=True)
    data = {key: value for key, value in command["payload"].items() if key != "batch_uuid"}
    service = mark_delivered if command["action"] == "mark_delivered" else confirm_delivery
    return service(batch_id=int(mapping.source_pk), **data), mapping


def review(command, actor, state):
    from apps.mobile_sync.errors import SyncError
    from apps.mobile_sync.models import SyncEntity
    from apps.poultry.services.operations import review_adjustment
    mapping = SyncEntity.objects.filter(stream=state["stream"], entity_type="poultry.adjustment_proposal",
        entity_uuid=command["entity_uuid"], deleted=False).first()
    if mapping is None:
        raise SyncError("reference_unavailable", "Proposal is unavailable.")
    assert_revision(command, mapping, state)
    proposal = review_adjustment(proposal_id=int(mapping.source_pk), reviewed_by=actor,
        approve=command["action"] == "approve", reason=command["payload"]["reason"])
    batch_mapping = SyncEntity.objects.get(stream=state["stream"], entity_type="poultry.batch", source_pk=str(proposal.batch_id))
    return proposal, batch_mapping


def recalculate(command, actor, state):
    from apps.poultry.models import Batch
    from apps.poultry.services.feed_metrics import recalculate_feed_event_populations
    mapping = resolve_batch(command, state, expected=True)
    batch = Batch.objects.select_for_update().get(pk=int(mapping.source_pk))
    recalculate_feed_event_populations(batch)
    return batch, mapping


@dataclass(frozen=True)
class CommandSpec:
    capability: str
    roles: frozenset
    mode: str
    handler: object
    affected_entities: tuple
    mutates_existing: bool = False


REGISTRY = {
    ("poultry.mortality", "record", 1): CommandSpec("poultry.capture", frozenset(OPERATORS), "queued",
        mortality_record, ("poultry.batch", "poultry.mortality", "poultry.feed_usage")),
}

from apps.poultry.services.feed_metrics import record_feed_usage
from apps.poultry.services.operations import record_treatment, record_weight, propose_adjustment

REGISTRY.update({
    ("poultry.batch", "book", 1): CommandSpec("poultry.manage_batch", frozenset(SUPERVISORS), "queued", book, ("poultry.batch",)),
    ("poultry.batch", "mark_delivered", 1): CommandSpec("poultry.manage_batch", frozenset(SUPERVISORS), "queued", delivery, ("poultry.batch",), True),
    ("poultry.batch", "confirm_delivery", 1): CommandSpec("poultry.manage_batch", frozenset(SUPERVISORS), "queued", delivery, ("poultry.batch",), True),
    ("poultry.feed_usage", "record", 1): CommandSpec("poultry.capture", frozenset(OPERATORS), "queued", append_record(record_feed_usage, "poultry.feed_usage"), ("poultry.batch", "poultry.feed_usage")),
    ("poultry.treatment", "record", 1): CommandSpec("poultry.capture", frozenset(OPERATORS), "queued", append_record(record_treatment, "poultry.treatment"), ("poultry.batch", "poultry.treatment")),
    ("poultry.weight_sample", "record", 1): CommandSpec("poultry.capture", frozenset(OPERATORS), "queued", append_record(record_weight, "poultry.weight_sample"), ("poultry.batch", "poultry.weight_sample")),
    ("poultry.adjustment_proposal", "propose", 1): CommandSpec("poultry.correct", frozenset(SUPERVISORS), "queued", append_record(propose_adjustment, "poultry.adjustment_proposal"), ("poultry.adjustment_proposal",)),
    ("poultry.adjustment_proposal", "approve", 1): CommandSpec("poultry.correct", frozenset(SUPERVISORS), "online", review, ("poultry.batch", "poultry.flock_adjustment", "poultry.adjustment_proposal", "poultry.feed_usage"), True),
    ("poultry.adjustment_proposal", "reject", 1): CommandSpec("poultry.correct", frozenset(SUPERVISORS), "online", review, ("poultry.adjustment_proposal",), True),
    ("poultry.batch", "recalculate_feed", 1): CommandSpec("poultry.correct", frozenset(SUPERVISORS), "online", recalculate, ("poultry.batch", "poultry.feed_usage"), True),
})
