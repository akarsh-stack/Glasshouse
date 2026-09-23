import logging
from pathlib import Path

from sqlmodel import Session, select

from ..models import Document
from .ingestion import UnsupportedDocument

logger = logging.getLogger(__name__)

# backend/app/services/seeding.py -> repo root -> samples/
SAMPLES_DIR = Path(__file__).resolve().parents[3] / "samples"

# Only formats `_extract_pages` actually understands. Without this, anything in
# the directory gets seeded: unknown extensions fall through to "decode as
# UTF-8 with errors=replace", so a stray .db or .DS_Store becomes a document
# full of mojibake that then competes in retrieval.
SEEDABLE_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".pdf", ".docx"})


async def seed_samples(ingest_service, engine) -> int:
    """Ingest `samples/` when the store is empty. Returns documents added.

    A fresh deploy has nothing to ask about, and the starter questions are
    derived from what's loaded — so an unseeded instance greets a visitor with
    an empty rail and no way in. On a host without a persistent disk that is the
    state after every restart.

    Two guards make this safe to run on every boot: it does nothing when any
    document already exists, so it can never duplicate or clobber a real corpus;
    and a file that won't parse is logged and skipped rather than taking the
    whole startup down with it.
    """
    with Session(engine) as db:
        if db.exec(select(Document)).first() is not None:
            return 0

    if not SAMPLES_DIR.is_dir():
        logger.warning(f"SEED_SAMPLES set but {SAMPLES_DIR} is missing; nothing to seed")
        return 0

    added = 0
    for path in sorted(SAMPLES_DIR.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SEEDABLE_SUFFIXES:
            logger.debug(f"Skipping non-document {path.name}")
            continue
        try:
            with Session(engine) as db:
                await ingest_service.ingest_document(path.read_bytes(), path.name, db)
            added += 1
        except (UnsupportedDocument, OSError) as e:
            logger.warning(f"Skipped sample {path.name}: {e}")
        except Exception as e:  # noqa: BLE001
            # Seeding is a convenience. Nothing here justifies refusing to boot.
            logger.error(f"Unexpected error seeding {path.name}: {e}")

    if added:
        logger.info(f"Seeded {added} sample document(s) from {SAMPLES_DIR}")
    return added
