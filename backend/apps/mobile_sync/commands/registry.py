"""The only enabled implementation in v1; never dispatch arbitrary model CRUD."""
from dataclasses import dataclass

from apps.mobile_sync.policy import OPERATORS


def mortality_record(command, actor, state):
    from apps.mobile_sync.errors import SyncError
    from apps.mobile_sync.models import SyncEntity
    from apps.poultry.services.batch_lifecycle import create_mortality_with_lifecycle
    mapping = SyncEntity.objects.filter(stream=state["stream"], entity_uuid=command["payload"]["batch_uuid"],
                                        entity_type="poultry.batch", deleted=False).first()
    if mapping is None:
        raise SyncError("reference_unavailable", "Batch reference is unavailable.")
    data = dict(command["payload"])
    data.pop("batch_uuid")
    mortality = create_mortality_with_lifecycle(batch_id=int(mapping.source_pk), created_by=actor, **data)
    state["entity_ids"][("poultry.mortality", str(mortality.pk))] = command["entity_uuid"]
    return mortality, mapping


@dataclass(frozen=True)
class CommandSpec:
    capability: str
    roles: frozenset
    mode: str
    handler: object
    affected_entities: tuple


REGISTRY = {
    ("poultry.mortality", "record", 1): CommandSpec("poultry.capture", frozenset(OPERATORS), "queued",
        mortality_record, ("poultry.batch", "poultry.mortality", "poultry.feed_usage")),
}
