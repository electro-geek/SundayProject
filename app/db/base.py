from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


# NOTE: model classes are registered on ``Base.metadata`` by importing
# ``app.models`` (see app/models/__init__.py). Importing them here would create
# a circular import because each model imports ``Base`` from this module.
