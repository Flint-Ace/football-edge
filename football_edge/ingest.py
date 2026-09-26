"""Ingest: adapters -> store. Also owns closing-line detection and
result recording. Adapters never do this themselves."""
from datetime import datetime, timezone
from typing import List

from .adapters.base import Adapter, AdapterResult
from .store import Store


def ingest(store: Store, league: str, adapters: List[Adapter], **fetch_kw) -> dict:
    summary = {"league": league, "adapters": {}}
    now = datetime.now(timezone.utc).isoformat()
    for ad in adapters:
        try:
            res: AdapterResult = ad.fetch(league, **fetch_kw)
        except Exception as e:
            store.log(now, league, ad.name, 0, 0, 0, [f"fetch failed: {e}"])
            q = getattr(ad, "quota", {}) or {}
            store.set_status(ad.name, league, now, False, error=str(e), quota_remaining=q.get("remaining"), quota_used=q.get("used"))
            summary["adapters"][ad.name] = {"error": str(e)}
            continue
        n_lines = n_splits = 0
        for g in res.games:
            store.upsert_game(g)
        for ref, obs in res.lines.items():
            gid = store.resolve_game_id(league, ref)
            if not gid:
                res.errors.append(f"unresolved game ref for lines: {ref}"); continue
            for o in obs:
                n_lines += int(store.add_line(gid, o))
        for ref, obs in res.splits.items():
            gid = store.resolve_game_id(league, ref)
            if not gid:
                res.errors.append(f"unresolved game ref for splits: {ref}"); continue
            for o in obs:
                n_splits += int(store.add_split(gid, o))
        for ref, r in res.results.items():
            gid = store.resolve_game_id(league, ref)
            g = store.get_game(gid) if gid else None
            if not g:
                res.errors.append(f"unresolved game ref for result: {ref}"); continue
            from .schema import Game, Team
            g.update(status="final", score_away=r["away_score"], score_home=r["home_score"], final_ts=r.get("final_ts", now), updated_at=now)
            store.conn.execute("UPDATE games SET status=?, json=?, updated_at=? WHERE id=?", ("final", __import__("json").dumps(g), now, gid))
        for ref, notes in getattr(res, "notes", {}).items():
            gid = store.resolve_game_id(league, ref)
            if not gid:
                res.errors.append(f"unresolved game ref for notes: {ref}"); continue
            for n in notes:
                store.add_note(gid, n["ts"], n.get("kind", "General"), n["text"])
        store.log(now, league, ad.name, len(res.games), n_lines, n_splits, res.errors)
        q = getattr(ad, "quota", {}) or {}
        skipped = any("not set" in e or "skipped" in e or "UNAVAILABLE" in e for e in res.errors)
        hard = [e for e in res.errors if e.startswith("cfbd /") or e.startswith("odds_api /")]
        store.set_status(ad.name, league, now, ok=not skipped and not hard,
                         error="; ".join(res.errors[:6]) if (skipped or hard) else "",
                         games=len(res.games), lines=n_lines, splits=n_splits,
                         quota_remaining=q.get("remaining"), quota_used=q.get("used"),
                         extra={"errors": res.errors[:40], "unresolved": sum(1 for e in res.errors if e.startswith("unresolved"))})
        summary["adapters"][ad.name] = {"games": len(res.games), "new_lines": n_lines, "new_splits": n_splits, "errors": res.errors}
    detect_closes(store, league)
    store.commit()
    return summary


def detect_closes(store: Store, league: str):
    """Once a game is in progress or final, the last non-opener observation
    at or before kickoff for each provider+book becomes the closing line.
    If none exists before kickoff (sparse polling), the latest observation
    is used and the note says so."""
    for g in store.games(league):
        if g["status"] not in ("in_progress", "final"):
            continue
        for provider, book in store.books_for(g["id"]):
            if store.has_close(g["id"], provider, book):
                continue
            row = store.latest_pre_kickoff(g["id"], provider, book, g["kickoff_utc"]) or store.latest_any(g["id"], provider, book)
            if row:
                store.mark_close(row[0])
