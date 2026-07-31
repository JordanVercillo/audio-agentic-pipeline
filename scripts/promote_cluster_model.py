"""promote_cluster_model.py — review a trained model, then serve it (D-62).

Training is automatic and changes nothing a visitor sees. THIS is the step that
moves identities, so it prints the diff and, unless the retrain is
identity-stable, requires an explicit --promote.

    uv run python scripts/promote_cluster_model.py                 # status
    uv run python scripts/promote_cluster_model.py --model 12      # the diff
    uv run python scripts/promote_cluster_model.py --model 12 --promote
    uv run python scripts/promote_cluster_model.py --train         # train, then diff

Why a human is in this loop: promoting rewrites which bucket a visitor's
"home sound" is, what the legend colours mean, and can move the archetype
narrative. Session 50's retrain moved the owner's archetype; that was ratified,
not silently applied (D-55(d)). The identity-stable case is the exception —
same k, matched centroids, unchanged words — because then nothing a visitor
can perceive has moved.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# A Windows cp1252 console cannot print this script's arrows/em-dashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.store import clusters as cl  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402


def _fmt(v, nd=3):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _unpromote(cache: FeatureCache, model_id: int, kind: str, *,
               force: bool = False) -> int:
    """Roll back a promotion by clearing promoted_at, and say what now serves.

    This used to be unsafe to do by hand: `_backfill_promoted_at` ran on every
    `FeatureCache()` construction — and the webapp builds one per request — so
    clearing the only promoted row meant the next HTTP request auto-promoted
    the newest UNREVIEWED candidate, which is exactly the thing D-62 exists to
    prevent. That backfill is now a one-shot marked in `schema_migrations`, so
    the rollback holds.
    """
    from sqlalchemy import text

    with cache.engine.begin() as conn:
        row = conn.execute(text(
            "SELECT promoted_at FROM cluster_models WHERE id = :i"),
            {"i": model_id}).fetchone()
        if row is None:
            print(f"no cluster model with id {model_id}")
            return 1
        if row[0] is None:
            print(f"model {model_id} is not promoted — nothing to roll back")
            return 0
        # Learned the hard way while testing this verb: `promoted_at` on a
        # SUPERSEDED model is history, not a switch. Clearing it changes
        # nothing about what serves and cannot be undone (the timestamp is
        # gone). Rollback means "stop serving the thing that serves".
        served = cl.latest_model(cache, kind)
        if served is not None and served.id != model_id and not force:
            print(f"model {model_id} is not the served model — {served.id} is.")
            print("  Its promoted_at is HISTORY: clearing it changes nothing about")
            print("  what visitors see and the timestamp cannot be recovered.")
            print(f"  To roll back what is actually serving:  --unpromote {served.id}")
            print("  To erase this historical record anyway:  --force")
            return 1
        conn.execute(text(
            "UPDATE cluster_models SET promoted_at = NULL WHERE id = :i"),
            {"i": model_id})

    now = cl.latest_model(cache, kind)
    print(f"model {model_id} is no longer served.")
    if now is None:
        print("  ⚠ NOTHING is promoted for this kind now. The surfaces that read")
        print("    a served model will render empty until you promote one:")
        print("      uv run python scripts/promote_cluster_model.py --model <id> --promote")
    else:
        print(f"  now serving: model {now.id} (k={now.k}, promoted {now.promoted_at})")
        print("  NEXT: uv run python scripts/build_feature_marts.py  (reproject)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", default="song", choices=["song", "artist"])
    ap.add_argument("--model", type=int, help="model id to review/promote")
    ap.add_argument("--train", action="store_true", help="train a new model first")
    ap.add_argument("--promote", action="store_true", help="actually promote")
    ap.add_argument("--unpromote", type=int, metavar="MODEL",
                    help="stop serving MODEL — the rollback verb (D-62)")
    ap.add_argument("--force", action="store_true",
                    help="with --unpromote: allow clearing a SUPERSEDED model's "
                         "promoted_at (history, not serving)")
    args = ap.parse_args()

    cache = FeatureCache()

    if args.unpromote:
        return _unpromote(cache, args.unpromote, args.kind, force=args.force)

    if args.train:
        print(f"training a new {args.kind} model ...")
        fn = cl.train_song_clusters if args.kind == "song" else cl.train_artist_clusters
        res = fn(cache)
        if not res:
            print("  training produced no model (too few tracks?)")
            return 1
        print(f"  trained model {res['model_id']}: k={res['k']} "
              f"silhouette={res['silhouette']} labels={res['labels']}")
        if res.get("promoted"):
            print("  promoted on bootstrap (no prior model) — nothing to ratify")
            return 0
        args.model = args.model or res["model_id"]

    served = cl.latest_model(cache, args.kind)
    newest = cl.newest_model(cache, args.kind)

    f = cl.freshness(cache, args.kind)
    print(f"\n── {args.kind} freshness ──")
    print(f"  serving model : {served.id if served else '(none)'}")
    print(f"  population    : {f['n_population']}")
    print(f"  trained on    : {_fmt(f['n_trained'])}")
    print(f"  coverage      : {_fmt(f['coverage'], 4)}")
    print(f"  growth ratio  : {_fmt(f['growth_ratio'])}")
    print(f"  stale         : {f['stale']}  {f['reasons'] or ''}")
    if f["descriptions_missing"]:
        print("  ⚠ the serving model has NO descriptions — the legend renders blank")

    target_id = args.model or (newest.id if newest else None)
    if target_id is None or (served and target_id == served.id):
        print("\nnothing to promote.")
        return 0

    with cache._Session() as s:
        from src.store.models import ClusterModel  # noqa: PLC0415
        target = s.get(ClusterModel, target_id)
        if target is None:
            print(f"\nno model with id {target_id}")
            return 1
        t_k, t_labels = target.k, dict(target.labels)
        t_sil, t_n = target.silhouette, target.n_trained

    print(f"\n── candidate model {target_id} ──")
    print(f"  k={t_k}  silhouette={_fmt(t_sil)}  n_trained={_fmt(t_n)}")
    for cid, lbl in sorted(t_labels.items(), key=lambda kv: int(kv[0])):
        print(f"    {cid}: {lbl}")

    identity_map = None
    if served is not None:
        identity_map = cl.match_identity(served, target) if target_id != served.id else None
        print("\n── identity vs the serving model ──")
        if identity_map:
            print("  ✅ IDENTITY-STABLE — same k, centroids matched, words unchanged.")
            for new, old in sorted(identity_map.items(), key=lambda kv: int(kv[0])):
                arrow = "(unchanged)" if int(new) == old else f"→ remapped to slot {old}"
                print(f"    new {new} {arrow}  '{t_labels[new]}'")
            print("  Promoting is safe to automate: nothing a visitor can perceive moves.")
        else:
            print("  ⚠ NOT identity-stable — this promotion CHANGES what visitors see.")
            print(f"    serving k={served.k}: {dict(served.labels)}")
            print(f"    candidate k={t_k}: {t_labels}")
            print("    (differing k, an unmatched centroid, or a renamed bucket)")
            print("    Cluster colours, the archetype's home bucket and the")
            print("    narrative may all move. This is the owner's call.")

    if not args.promote:
        print(f"\n(dry run) to apply:  uv run python scripts/promote_cluster_model.py "
              f"--kind {args.kind} --model {target_id} --promote")
        return 0

    res = cl.promote_model(cache, target_id, identity_map=identity_map)
    print(f"\n✅ promoted model {target_id} (remapped={res['remapped']})")
    print(f"   labels now: {res['labels']}")
    if f["descriptions_missing"] or True:
        print("   NEXT: uv run python scripts/describe_clusters.py   (legend prose)")
        print("         uv run python scripts/build_feature_marts.py (mart projection)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
