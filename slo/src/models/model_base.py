"""SQLAlchemy declarative base with CamelCase → snake_case table naming."""
import re
from typing import Any

from sqlalchemy.orm import as_declarative, declared_attr


def resolve_table_name(name: str) -> str:
    """Convert ``CamelCase`` class name to ``snake_case`` table name."""
    names = re.split(pattern="(?=[A-Z])", string=name)
    return "_".join(x.lower() for x in names if x)


class CustomBase:
    """Shared base behaviour for every domain SQLAlchemy model."""

    __repr_attrs__: list = []
    __repr_max_length__: int = 15

    @declared_attr
    def __tablename__(cls) -> str:
        return resolve_table_name(name=cls.__name__)

    def dict(self) -> dict[str, Any]:
        """Return the model's column → value mapping as a plain dict."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class_registry: dict[str, Any] = {}


@as_declarative(class_registry=class_registry)
class Base(CustomBase):
    id: Any
    __name__: str
