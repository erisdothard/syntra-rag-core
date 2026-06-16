"""
clients/logistics/schema.py

Client-specific Pydantic validation models for the logistics assistant.

Domain rules:
- Carrier chunks MUST have an MC or DOT number
- Rate chunks MUST have origin and destination
- Service chunks MUST have a service type
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CarrierChunkSchema(BaseModel):
    """Domain validation for a Carrier profile chunk."""

    domain_key: str = Field(description="MC or DOT number")
    kind: Literal["Carrier"]
    variant: None = None
    content: str
    metadata: CarrierMetadata


class CarrierMetadata(BaseModel):
    name: str
    authority: str
    equipment: list[str] = Field(default_factory=list)


class RateChunkSchema(BaseModel):
    """Domain validation for a Rate sheet chunk."""

    domain_key: str = Field(description="Lane ID")
    kind: Literal["Rate"]
    variant: str | None = None
    content: str
    metadata: RateMetadata


class RateMetadata(BaseModel):
    origin: str
    destination: str
    rate_per_mile: float
    equipment: str


class ServiceChunkSchema(BaseModel):
    """Domain validation for a Service standard chunk."""

    domain_key: str = Field(description="Service ID")
    kind: Literal["Service"]
    variant: str | None = None
    content: str
    metadata: ServiceMetadata


class ServiceMetadata(BaseModel):
    service_type: str
    sla: dict = Field(default_factory=dict)


_SCHEMA_MAP = {
    "Carrier": CarrierChunkSchema,
    "Rate": RateChunkSchema,
    "Service": ServiceChunkSchema,
}


def validate_domain_chunk(chunk_dict: dict) -> BaseModel:
    """Validate a logistics chunk against its domain schema."""
    kind = chunk_dict.get("kind")
    schema_cls = _SCHEMA_MAP.get(kind)
    if schema_cls is None:
        raise ValueError(f"No logistics schema for kind '{kind}'")
    return schema_cls(**chunk_dict)
