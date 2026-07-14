"""Idempotent Milvus schema bootstrap used during application startup."""

import logging

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, db, utility

from app.config import settings

logger = logging.getLogger(__name__)
_ALIAS = "rca_bootstrap"


def _connection_parameters() -> dict[str, str | int]:
    endpoint = settings.MILVUS_URI.replace("http://", "").replace("https://", "")
    host, port = endpoint.rsplit(":", 1) if ":" in endpoint else (endpoint, "19530")
    user, password = settings.MILVUS_TOKEN.split(":", 1) if ":" in settings.MILVUS_TOKEN else ("root", "Milvus")
    return {"host": host, "port": port, "user": user, "password": password, "timeout": 5}


def check_milvus_connection() -> bool:
    """Probe the Milvus protocol, not only whether its TCP port is open."""
    alias = "rca_readiness"
    try:
        connections.connect(alias=alias, **_connection_parameters())
        db.list_database(using=alias)
        return True
    except Exception:
        return False
    finally:
        if connections.has_connection(alias):
            connections.disconnect(alias)


def ensure_milvus_schema() -> bool:
    """Create the configured database and knowledge collection when missing."""
    try:
        connections.connect(alias=_ALIAS, **_connection_parameters())
        databases = db.list_database(using=_ALIAS)
        if settings.MILVUS_DATABASE not in databases:
            db.create_database(settings.MILVUS_DATABASE, using=_ALIAS)
            logger.info("Created Milvus database: %s", settings.MILVUS_DATABASE)
        db.using_database(settings.MILVUS_DATABASE, using=_ALIAS)

        collection_exists = utility.has_collection(settings.MILVUS_COLLECTION, using=_ALIAS)
        if collection_exists:
            existing = Collection(settings.MILVUS_COLLECTION, using=_ALIAS)
            embedding_field = next((field for field in existing.schema.fields if field.name == "embedding"), None)
            actual_dim = embedding_field.params.get("dim") if embedding_field else None
            if actual_dim != settings.MILVUS_DIM:
                if existing.num_entities:
                    logger.error(
                        "Milvus collection dimension mismatch: configured=%s actual=%s entities=%s. "
                        "Run the rebuild script before changing embedding models.",
                        settings.MILVUS_DIM,
                        actual_dim,
                        existing.num_entities,
                    )
                    return False
                utility.drop_collection(settings.MILVUS_COLLECTION, using=_ALIAS)
                collection_exists = False
                logger.warning(
                    "Recreating empty Milvus collection after dimension change: %s -> %s",
                    actual_dim,
                    settings.MILVUS_DIM,
                )

        if not collection_exists:
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                    FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
                    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
                    FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.MILVUS_DIM),
                ],
                description="DataAgent knowledge base",
                enable_dynamic_field=True,
            )
            collection = Collection(settings.MILVUS_COLLECTION, schema=schema, using=_ALIAS)
            collection.create_index(
                field_name="embedding",
                index_params={"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
            )
            logger.info("Created Milvus collection: %s", settings.MILVUS_COLLECTION)
        return True
    except Exception:
        logger.exception("Milvus bootstrap failed; knowledge features are degraded")
        return False
    finally:
        if connections.has_connection(_ALIAS):
            connections.disconnect(_ALIAS)
