"""
clients/logistics/parser.py

DomainParser implementation for logistics carrier document data.

Handles:
- Carrier profiles (company info, authority, insurance)
- Rate sheets (lane-based pricing)
- Service standards (transit times, accessorials)

This proves the architecture: a non-healthcare client runs on the
same core with zero core changes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from core.interfaces import Chunk

logger = logging.getLogger(__name__)

# Document types we extract
_DOC_TYPES = frozenset({"carrier", "rate", "service"})


class LogisticsParser:
    """DomainParser for logistics carrier documents."""

    def parse(self, raw_path: str) -> Iterable[Chunk]:
        """Parse a logistics JSON document and yield Chunks."""
        path = Path(raw_path)
        if not path.exists():
            logger.warning("File not found: %s", path)
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Cannot read %s: %s", path, exc)
            return

        # Handle both single docs and arrays
        docs = data if isinstance(data, list) else [data]

        for doc in docs:
            doc_type = doc.get("type", "").lower()
            if doc_type not in _DOC_TYPES:
                continue

            chunk = _doc_to_chunk(doc, doc_type)
            if chunk is not None:
                yield chunk

    def dedup_key(self, chunk: Chunk) -> str:
        """Dedup key: domain_key + kind."""
        return f"{chunk.domain_key or 'none'}|{chunk.kind}"


def _doc_to_chunk(doc: dict, doc_type: str) -> Chunk | None:
    """Convert a logistics document to a Chunk."""
    if doc_type == "carrier":
        return _carrier_to_chunk(doc)
    if doc_type == "rate":
        return _rate_to_chunk(doc)
    if doc_type == "service":
        return _service_to_chunk(doc)
    return None


def _carrier_to_chunk(doc: dict) -> Chunk | None:
    """Convert a carrier profile to a Chunk."""
    mc_number = doc.get("mc_number", "")
    name = doc.get("name", "Unknown Carrier")
    dot_number = doc.get("dot_number", "")
    authority = doc.get("authority_status", "unknown")
    insurance = doc.get("insurance", {})

    content_lines = [
        f"Document: Carrier Profile",
        f"Carrier: {name}",
        f"MC Number: {mc_number}",
        f"DOT Number: {dot_number}",
        f"Authority: {authority}",
    ]

    if insurance:
        liability = insurance.get("liability", "N/A")
        cargo = insurance.get("cargo", "N/A")
        content_lines.append(f"Insurance — Liability: {liability}, Cargo: {cargo}")

    equipment = doc.get("equipment_types", [])
    if equipment:
        content_lines.append(f"Equipment: {', '.join(equipment)}")

    service_area = doc.get("service_area", [])
    if service_area:
        content_lines.append(f"Service area: {', '.join(service_area)}")

    return Chunk(
        domain_key=mc_number or dot_number,
        kind="Carrier",
        variant=None,
        content="\n".join(content_lines),
        metadata={
            "name": name,
            "authority": authority,
            "equipment": equipment,
        },
    )


def _rate_to_chunk(doc: dict) -> Chunk | None:
    """Convert a rate sheet entry to a Chunk."""
    lane_id = doc.get("lane_id", "")
    origin = doc.get("origin", "")
    destination = doc.get("destination", "")
    rate_per_mile = doc.get("rate_per_mile", 0)
    flat_rate = doc.get("flat_rate")
    equipment = doc.get("equipment_type", "Dry Van")
    transit_days = doc.get("transit_days", "N/A")

    content_lines = [
        f"Document: Rate Sheet",
        f"Lane: {origin} → {destination}",
        f"Lane ID: {lane_id}",
        f"Equipment: {equipment}",
        f"Rate per mile: ${rate_per_mile:.2f}" if rate_per_mile else "",
    ]

    if flat_rate is not None:
        content_lines.append(f"Flat rate: ${flat_rate:,.2f}")

    content_lines.append(f"Transit: {transit_days} days")

    min_weight = doc.get("min_weight")
    if min_weight:
        content_lines.append(f"Min weight: {min_weight} lbs")

    return Chunk(
        domain_key=lane_id,
        kind="Rate",
        variant=equipment.lower().replace(" ", "_"),
        content="\n".join(line for line in content_lines if line),
        metadata={
            "origin": origin,
            "destination": destination,
            "rate_per_mile": rate_per_mile,
            "equipment": equipment,
        },
    )


def _service_to_chunk(doc: dict) -> Chunk | None:
    """Convert a service standard document to a Chunk."""
    service_id = doc.get("service_id", "")
    service_type = doc.get("service_type", "")
    description = doc.get("description", "")
    sla = doc.get("sla", {})

    content_lines = [
        f"Document: Service Standard",
        f"Service: {service_type}",
        f"ID: {service_id}",
        f"Description: {description}",
    ]

    if sla:
        pickup_window = sla.get("pickup_window", "N/A")
        delivery_window = sla.get("delivery_window", "N/A")
        on_time_target = sla.get("on_time_target", "N/A")
        content_lines.extend([
            f"SLA — Pickup window: {pickup_window}",
            f"SLA — Delivery window: {delivery_window}",
            f"SLA — On-time target: {on_time_target}",
        ])

    accessorials = doc.get("accessorials", [])
    if accessorials:
        content_lines.append(f"Accessorials: {', '.join(accessorials)}")

    return Chunk(
        domain_key=service_id,
        kind="Service",
        variant=service_type.lower().replace(" ", "_") if service_type else None,
        content="\n".join(content_lines),
        metadata={
            "service_type": service_type,
            "sla": sla,
        },
    )
