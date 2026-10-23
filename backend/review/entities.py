"""Entity curation for the Console's EntitiesPage (file 08 §4.2, §4.4; file 05 entities). Owner: S1.

Search canonical names and aliases with counts. A merge re-points the source entity's aliases and mentions
to the target, keeps the source's canonical name as an alias of the target (so enrichment maps it there
from now on), updates ``documents.entity_ids`` and deletes the source; file 05 has no ``merged_into``
column. A split moves the chosen aliases, and the mentions whose surface has one of their keys, to a new
entity. Keys come from S2's ``canonical_key``. Every action writes ``audit_events`` (entity).
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from backend.llm_engine.enrichment.entities import canonical_key
from backend.postgres.enums import AuditEntityType, EntityCreatedBy, EntityType
from backend.postgres.models import AuditEvent, Document, Entity, EntityAlias, EntityMention


class EntityError(ValueError):
    pass


class AliasView(BaseModel):
    alias: str
    alias_key: str
    created_by: str


class EntityView(BaseModel):
    entity_id: uuid.UUID
    type: EntityType
    canonical_name: str
    canonical_key: str
    created_by: str
    aliases: list[AliasView]
    mentions: int
    documents: int


class EntityPage(BaseModel):
    items: list[EntityView]
    total: int


class MergeRequest(BaseModel):
    target_entity_id: uuid.UUID = Field(description="the entity that stays")
    source_entity_ids: list[uuid.UUID] = Field(min_length=1, description="entities folded into the target")


class SplitRequest(BaseModel):
    entity_id: uuid.UUID
    alias_keys: list[str] = Field(min_length=1, description="aliases that move to the new entity")
    canonical_name: str = Field(min_length=1, description="the new entity's canonical name")


def _view(session: Session, entity: Entity) -> EntityView:
    aliases = session.scalars(
        select(EntityAlias).where(EntityAlias.entity_id == entity.entity_id).order_by(EntityAlias.alias)
    )
    mentions, documents = session.execute(
        select(func.count(), func.count(func.distinct(EntityMention.doc_id))).where(
            EntityMention.entity_id == entity.entity_id
        )
    ).one()
    return EntityView(
        entity_id=entity.entity_id,
        type=entity.type,
        canonical_name=entity.canonical_name,
        canonical_key=entity.canonical_key,
        created_by=entity.created_by,
        aliases=[AliasView(alias=a.alias, alias_key=a.alias_key, created_by=a.created_by) for a in aliases],
        mentions=mentions,
        documents=documents,
    )


def search(
    session: Session, query: str = "", entity_type: EntityType | None = None, limit: int = 50, offset: int = 0
) -> EntityPage:
    stmt = select(Entity)
    if query:
        pattern = f"%{query.strip()}%"
        alias_hit = select(EntityAlias.entity_id).where(EntityAlias.alias.ilike(pattern))
        stmt = stmt.where(or_(Entity.canonical_name.ilike(pattern), Entity.entity_id.in_(alias_hit)))
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(Entity.canonical_name).limit(limit).offset(offset)).all()
    return EntityPage(items=[_view(session, e) for e in rows], total=total or 0)


def _audit(session: Session, actor: str, entity_id: uuid.UUID, action: str, before, after) -> None:
    session.add(
        AuditEvent(
            actor=actor,
            entity_type=AuditEntityType.ENTITY,
            entity_id=str(entity_id),
            action=action,
            before=before,
            after=after,
        )
    )


def _replace_in_documents(session: Session, old: uuid.UUID, new: uuid.UUID) -> None:
    for document in session.scalars(select(Document).where(Document.entity_ids.any(old))):
        ids = [new if i == old else i for i in document.entity_ids]
        document.entity_ids = list(dict.fromkeys(ids))


def merge(session: Session, request: MergeRequest, actor: str) -> EntityView:
    target = session.get(Entity, request.target_entity_id)
    if target is None:
        raise LookupError(f"entity {request.target_entity_id}")
    for source_id in request.source_entity_ids:
        source = session.get(Entity, source_id)
        if source is None:
            raise LookupError(f"entity {source_id}")
        if source.entity_id == target.entity_id:
            raise EntityError("an entity cannot be merged into itself")
        if source.type != target.type:
            raise EntityError(
                f"{source.canonical_name} is a {source.type}, {target.canonical_name} a {target.type}"
            )
        before = _view(session, source).model_dump(mode="json")
        session.execute(
            update(EntityAlias)
            .where(EntityAlias.entity_id == source.entity_id)
            .values(entity_id=target.entity_id)
        )
        session.execute(
            update(EntityMention)
            .where(EntityMention.entity_id == source.entity_id)
            .values(entity_id=target.entity_id)
        )
        if session.get(EntityAlias, (source.type, source.canonical_key)) is None:
            session.add(
                EntityAlias(
                    type=source.type,
                    alias_key=source.canonical_key,
                    entity_id=target.entity_id,
                    alias=source.canonical_name,
                    created_by="operator",
                )
            )
        _replace_in_documents(session, source.entity_id, target.entity_id)
        session.flush()
        session.delete(source)
        _audit(session, actor, target.entity_id, "merge", before, {"into": str(target.entity_id)})
    session.flush()
    return _view(session, target)


def split(session: Session, request: SplitRequest, actor: str) -> EntityView:
    entity = session.get(Entity, request.entity_id)
    if entity is None:
        raise LookupError(f"entity {request.entity_id}")
    keys = set(request.alias_keys)
    aliases = session.scalars(
        select(EntityAlias).where(EntityAlias.entity_id == entity.entity_id, EntityAlias.alias_key.in_(keys))
    ).all()
    if {a.alias_key for a in aliases} != keys:
        raise EntityError(
            f"not aliases of {entity.canonical_name}: {sorted(keys - {a.alias_key for a in aliases})}"
        )
    new_key = canonical_key(request.canonical_name)
    if session.scalar(
        select(Entity.entity_id).where(Entity.type == entity.type, Entity.canonical_key == new_key)
    ):
        raise EntityError(f"a {entity.type} named {request.canonical_name!r} already exists; merge instead")
    new = Entity(
        type=entity.type,
        canonical_name=request.canonical_name.strip(),
        canonical_key=new_key,
        created_by=EntityCreatedBy.OPERATOR,
        first_seen_doc_id=entity.first_seen_doc_id,
    )
    session.add(new)
    session.flush()
    for alias in aliases:
        alias.entity_id = new.entity_id
    moved_docs = set()
    for mention in session.scalars(select(EntityMention).where(EntityMention.entity_id == entity.entity_id)):
        if canonical_key(mention.surface) in keys:
            mention.entity_id = new.entity_id
            moved_docs.add(mention.doc_id)
    session.flush()
    for doc_id in moved_docs:
        document = session.get(Document, doc_id)
        ids = list(document.entity_ids or [])
        still = session.scalar(
            select(EntityMention.mention_id)
            .where(EntityMention.doc_id == doc_id, EntityMention.entity_id == entity.entity_id)
            .limit(1)
        )
        ids = [i for i in ids if i != entity.entity_id or still is not None]
        document.entity_ids = [*ids, new.entity_id] if new.entity_id not in ids else ids
    _audit(
        session,
        actor,
        entity.entity_id,
        "split",
        {"aliases": sorted(keys)},
        {"new_entity_id": str(new.entity_id), "canonical_name": new.canonical_name},
    )
    session.flush()
    return _view(session, new)
