"""Walk the audit log's hash chain and report whether it's intact.

Run against firewall.db directly (no server needed):
    python scripts/verify_audit.py

Pass --tamper to first corrupt one row's `reason` field in a scratch copy
of the DB, proving the verifier actually catches tampering rather than
always reporting "intact".
"""
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.audit import verify_chain  # noqa: E402
from app.db import DB_PATH  # noqa: E402


def _tamper_scratch_copy() -> Path:
    """Copy firewall.db aside and corrupt one row, without touching the real DB."""
    scratch_path = DB_PATH.parent / "firewall.tamper-demo.db"
    shutil.copyfile(DB_PATH, scratch_path)

    conn = sqlite3.connect(scratch_path)
    row = conn.execute("SELECT id FROM audit_log ORDER BY id ASC LIMIT 1").fetchone()
    if row is None:
        conn.close()
        raise SystemExit("audit_log is empty — run a demo script against the server first.")
    conn.execute("UPDATE audit_log SET reason = 'TAMPERED' WHERE id = ?", row)
    conn.commit()
    conn.close()
    return scratch_path


def main() -> None:
    if "--tamper" in sys.argv:
        print("Corrupting a scratch copy of the DB (real firewall.db is untouched)...")
        scratch_path = _tamper_scratch_copy()

        import app.db as db_module

        original_path = db_module.DB_PATH
        db_module.DB_PATH = scratch_path
        try:
            intact, bad_id = verify_chain()
        finally:
            db_module.DB_PATH = original_path
            scratch_path.unlink()

        print(f"intact = {intact}, first bad entry id = {bad_id}")
        assert not intact, "expected tampering to be detected, but it wasn't"
        print("Tampering detected correctly: the chain broke exactly where the row was edited.")
        return

    intact, bad_id = verify_chain()
    if intact:
        print("Audit log chain is intact: no tampering detected.")
    else:
        print(f"Audit log chain is BROKEN starting at entry id={bad_id}.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
