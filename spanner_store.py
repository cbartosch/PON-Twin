"""
Cloud Spanner (emulator) datastore for the Malang PON digital twin.

The twin's data of record lives in a Spanner database. On a fresh emulator it is
seeded once from the JSON fixtures (pon_data.json + malang_sto.json). The MCP
server loads everything into memory at process start via load_twin().

Schema (single wide table keyed by collection):

    CREATE TABLE twin_records (
        collection STRING(64)  NOT NULL,   -- e.g. "olts", "homes", "_sto_root"
        ordinal    INT64       NOT NULL,    -- preserves list order
        record_id  STRING(256) NOT NULL,
        payload    JSON        NOT NULL,    -- the original object
    ) PRIMARY KEY (collection, ordinal)

Config comes from env (with sane emulator defaults):
    SPANNER_EMULATOR_HOST   host:port of the emulator (presence => emulator mode)
    SPANNER_PROJECT         default "twin-project"
    SPANNER_INSTANCE        default "twin-instance"
    SPANNER_DATABASE        default "twin"
"""
import os
import json

PROJECT  = os.environ.get("SPANNER_PROJECT", "twin-project")
INSTANCE = os.environ.get("SPANNER_INSTANCE", "twin-instance")
DATABASE = os.environ.get("SPANNER_DATABASE", "twin")

TABLE_DDL = [
    """CREATE TABLE twin_records (
        collection STRING(64)  NOT NULL,
        ordinal    INT64       NOT NULL,
        record_id  STRING(256) NOT NULL,
        payload    JSON        NOT NULL,
    ) PRIMARY KEY (collection, ordinal)"""
]


def spanner_configured() -> bool:
    """True when we should talk to Spanner (emulator host present + lib importable)."""
    if not os.environ.get("SPANNER_EMULATOR_HOST"):
        return False
    try:
        import google.cloud.spanner  # noqa: F401
        return True
    except Exception:
        return False


def _client():
    from google.cloud import spanner
    # With SPANNER_EMULATOR_HOST set, the client auto-uses anonymous creds + endpoint.
    return spanner.Client(project=PROJECT)


def _instance(client):
    config_name = f"{client.project_name}/instanceConfigs/emulator-config"
    inst = client.instance(INSTANCE, configuration_name=config_name, node_count=1)
    if not inst.exists():
        inst.create().result(120)
    return inst


def _database(inst, create_schema=False):
    ddl = TABLE_DDL if create_schema else []
    db = inst.database(DATABASE, ddl_statements=ddl)
    if not db.exists():
        db.create().result(120)
    return db


def _json_obj(d):
    from google.cloud.spanner_v1 import JsonObject
    return JsonObject(d)


def _iter_seed_rows(pon_path, sto_path):
    """Yield (collection, ordinal, record_id, payload_dict) from the JSON fixtures."""
    with open(pon_path, encoding="utf-8") as f:
        pon = json.load(f)
    for collection, value in pon.items():
        if isinstance(value, list):
            for i, item in enumerate(value):
                rid = None
                if isinstance(item, dict):
                    for k in ("olt_id", "pon_port_id", "primary_splitter_id", "odp_id",
                              "home_id", "area_id", "pole_id", "cable_id", "edge_id"):
                        if k in item:
                            rid = str(item[k]); break
                yield collection, i, rid or f"{collection}-{i}", item
        else:
            yield collection, 0, collection, value

    # Store the whole STO structure as one blob so server.py can use it verbatim.
    try:
        with open(sto_path, encoding="utf-8") as f:
            sto = json.load(f)
        yield "_sto_root", 0, "root", sto
    except FileNotFoundError:
        pass


def ensure_schema_and_seed(pon_path, sto_path, force=False):
    """Create instance/database/table if needed and seed if empty. Idempotent."""
    client = _client()
    inst = _instance(client)
    db = _database(inst, create_schema=True)

    # Already seeded?
    if not force:
        with db.snapshot() as snap:
            n = list(snap.execute_sql("SELECT COUNT(*) FROM twin_records"))[0][0]
        if n and n > 0:
            return {"seeded": False, "rows": n}

    rows = list(_iter_seed_rows(pon_path, sto_path))
    # Write in batches to stay well under mutation limits.
    BATCH = 400
    written = 0
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        with db.batch() as batch:
            batch.insert_or_update(
                table="twin_records",
                columns=("collection", "ordinal", "record_id", "payload"),
                values=[(c, o, rid, _json_obj(p)) for (c, o, rid, p) in chunk],
            )
        written += len(chunk)
    return {"seeded": True, "rows": written}


def load_twin():
    """Read all rows from Spanner and reconstruct (D, STO) exactly as the JSON files
    would have produced. Returns (data_dict, sto_dict_or_None)."""
    client = _client()
    inst = _instance(client)
    db = _database(inst, create_schema=False)

    collections = {}
    sto = None
    # NB: no server-side ORDER BY. Sorting ~68k rows in one query exceeds the
    # emulator's max_intermediate_byte_size (128 MB) sort buffer and fails the
    # whole read. We stream unordered and restore (collection, ordinal) order
    # client-side, which the emulator can serve row-by-row without buffering.
    with db.snapshot() as snap:
        results = snap.execute_sql(
            "SELECT collection, ordinal, payload FROM twin_records"
        )
        rows = []
        for collection, ordinal, payload in results:
            # payload arrives as a JsonObject (dict subclass) or str depending on version.
            if isinstance(payload, str):
                payload = json.loads(payload)
            else:
                payload = json.loads(json.dumps(payload))  # normalise to plain dict/list
            rows.append((collection, ordinal, payload))
    rows.sort(key=lambda r: (r[0], r[1]))
    for collection, _ordinal, payload in rows:
        if collection == "_sto_root":
            sto = payload
        else:
            collections.setdefault(collection, []).append(payload)
    return collections, sto


def wait_for_emulator(timeout_s=90):
    """Block until the emulator answers, or raise."""
    import time
    from google.api_core.exceptions import GoogleAPICallError, RetryError, ServiceUnavailable
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            client = _client()
            list(client.list_instance_configs())  # cheap admin RPC
            return True
        except (GoogleAPICallError, RetryError, ServiceUnavailable, Exception) as e:  # noqa
            last = e
            time.sleep(2)
    raise RuntimeError(f"Spanner emulator not reachable within {timeout_s}s: {last}")
