"""Loads seed rows into an empty database: `python -m scripts.seed seed.json`.

File format: [{"table": "<table>", "rows": [{"<column>": value, ...}]}] in insert order (parents first), or
{"rows": [...those blocks...], "objects": [{"key", "contentType", "data": <base64>}]} when seeded records hold files
(the objects go to the app's storage first, so their keys exist). Tables that already contain rows are skipped, so
restarting the container never duplicates data.
"""

import base64
import json
import sys

from sqlalchemy import create_engine, func, select
from sqlmodel import SQLModel

import src.modules  # noqa: F401
import src.modules.shared.infrastructure.models  # noqa: F401
from src.configs import config, get_logger

logger = get_logger("seed")


def upload(objects: list[dict]) -> None:
    try:
        from src.libs.storage import ensure_bucket, get_storage
    except ImportError:  # no storage library: nothing to upload to
        return
    ensure_bucket()
    storage = get_storage()
    for item in objects:
        if storage.stat(item["key"]) is None:
            storage.put(item["key"], base64.b64decode(item["data"]), item["contentType"])
    logger.info("seed objects uploaded", extra={"objects": len(objects)})


def main(path: str) -> None:
    blocks = json.loads(open(path, encoding="utf-8").read())
    if isinstance(blocks, dict):
        if blocks.get("objects"):
            upload(blocks["objects"])
        blocks = blocks.get("rows") or []
    engine = create_engine(config.db_url)
    with engine.begin() as connection:
        for block in blocks:
            table = SQLModel.metadata.tables[block["table"]]
            if connection.execute(select(func.count()).select_from(table)).scalar_one():
                logger.info("seed skipped: table not empty", extra={"table": table.name})
                continue
            if block["rows"]:
                connection.execute(table.insert(), block["rows"])
            logger.info("seeded", extra={"table": table.name, "rows": len(block["rows"])})


if __name__ == "__main__":
    main(sys.argv[1])
