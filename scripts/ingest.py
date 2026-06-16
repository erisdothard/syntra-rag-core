"""
Offline ingestion script: parse → chunk → dedup → embed → upsert to Supabase.

Usage:
    python scripts/ingest.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from clients.fhir_mapping.parser import FHIRParser
from core.ingestion.chunk import ingest
from core.ingestion.index import index_chunks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    data_dir = os.environ.get("FHIR_DATA_DIR", "")
    if not data_dir:
        logger.error("FHIR_DATA_DIR not set")
        sys.exit(1)

    source = Path(data_dir)
    if not source.is_dir():
        logger.error("FHIR_DATA_DIR is not a directory: %s", source)
        sys.exit(1)

    # Step 1: Parse + dedup
    parser = FHIRParser()
    chunks = ingest(parser, source)
    logger.info("Chunks after dedup: %d", len(chunks))

    if not chunks:
        logger.warning("No chunks to index — exiting")
        return

    # Step 2: Build dedup keys
    dedup_keys = [parser.dedup_key(c) for c in chunks]

    # Step 3: Embed + upsert
    count = await index_chunks(
        chunks,
        client_name="fhir_mapping",
        dedup_keys=dedup_keys,
    )
    logger.info("Done — %d chunks indexed to Supabase", count)


if __name__ == "__main__":
    asyncio.run(main())
