import secrets
from typing import Any

_HEX = set("0123456789abcdef")
try:
    from bson import ObjectId as _BsonObjectId
except Exception:  # pragma: no cover - exercised by desktop dependency test
    _BsonObjectId = None


def new_id() -> str:
    return secrets.token_hex(12)


def validate_id(value: str, label: str = "المعرّف") -> str:
    if not isinstance(value, str) or len(value) != 24 or any(c not in _HEX for c in value.lower()):
        from app.services.errors import ValidationError

        raise ValidationError(f"{label} غير صالح")
    return value.lower()


def to_object_id(value: str, label: str = "المعرّف") -> Any:
    clean = validate_id(str(value), label)
    return _BsonObjectId(clean) if _BsonObjectId is not None else clean


def serialize_id(value: object) -> str:
    return str(value)
