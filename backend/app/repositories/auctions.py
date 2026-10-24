from __future__ import annotations


class AuctionRepository:
    def __init__(self, db, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db
        self.tenant_id = tenant_id

    def get(self, rfq_id: int, *, for_update: bool = False):
        sql = "SELECT * FROM rfqs WHERE id = ? AND tenant_id = ?"
        if for_update:
            sql += " FOR UPDATE"
        return self.db.execute(sql, (rfq_id, self.tenant_id)).fetchone()

    def list(self, limit: int, offset: int):
        return self.db.execute(
            "SELECT * FROM rfqs WHERE tenant_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (self.tenant_id, limit, offset),
        ).fetchall()
