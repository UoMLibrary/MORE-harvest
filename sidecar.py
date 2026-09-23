#!/usr/bin/env python3
"""The per-paper sidecar: the durable INTRA-ARTICLE record of one transformation.

Written to ingested/{id}/metadata.json on ingest. This is the SOURCE OF TRUTH for what a
paper's transformation produced — identity, the route/provenance it came by, its ANZSRC
classification, the gate verdicts, and a full asset manifest (every figure, its source and
checksum). The DuckDB only ever holds a rebuildable PROJECTION of these files (see
ingest_log.index_sidecar / build_db), never the master — honouring "the database is
disposable; every fact lives in the files".

Schema `more-intra-article/1`. Kept deliberately flat and JSON so `read_json_auto` can
federate a folder of them straight into a DuckDB view.
"""
import hashlib
import json
import os
import time

from pipeline_versions import PIPELINE_VERSIONS

SCHEMA = "more-intra-article/1"
NAME = "metadata.json"


def _article_hash(out_dir):
    try:
        return hashlib.sha256(
            open(os.path.join(out_dir, "article.xml"), "rb").read()).hexdigest()[:16]
    except OSError:
        return None


def _manifest(out_dir, asset_source):
    adir = os.path.join(out_dir, "assets")
    out = []
    if os.path.isdir(adir):
        for f in sorted(os.listdir(adir)):
            p = os.path.join(adir, f)
            if os.path.isfile(p):
                out.append({"file": f, "bytes": os.path.getsize(p),
                            "sha256_16": hashlib.sha256(open(p, "rb").read()).hexdigest()[:16],
                            "source": asset_source})
    return out


def write(out_dir, *, work_id, mid, doi, journal, title, route, lane, asset_route,
          anzsrc, provisional_anzsrc, validate_pass, lint_pass, err_count, warn_count,
          asset_source, provenance, licence_pass=None, licence_uri=None, fidelity=None,
          gate_engine=None, gate_checked_at=None):
    """Assemble and atomically write ingested/{id}/metadata.json; return the sidecar dict.

    anzsrc: list of {level, code, label} (division -> group -> field)."""
    manifest = _manifest(out_dir, asset_source)
    # the engine stamp names only the gates that actually judged THIS package:
    # a package with no fidelity verdict must not claim a fidelity engine
    engine = dict(gate_engine or {})
    if fidelity is None:
        engine.pop("fidelity", None)
    sc = {
        "schema": SCHEMA,
        "identity": {"work_id": work_id, "mid": mid, "doi": doi,
                     "journal": journal, "title": title},
        "route": {"route": route, "lane": lane, "asset_route": asset_route,
                  "provenance": provenance},
        "classification": {"anzsrc": anzsrc, "provisional": bool(provisional_anzsrc)},
        # `engine` (content-hashes of the gate implementations that issued these
        # verdicts) + `checked_at` make every verdict DATED AND ATTRIBUTED: after
        # a gate hardening, regate.py finds packages whose engine differs from
        # today's and re-judges them — no more stale greens (the 2026-07-14 class).
        "gates": {"validate_pass": bool(validate_pass), "lint_pass": bool(lint_pass),
                  "errors": int(err_count), "warnings": int(warn_count),
                  "licence_pass": (None if licence_pass is None else bool(licence_pass)),
                  "licence_uri": licence_uri,
                  "both_pass": bool(validate_pass and lint_pass),
                  "engine": engine,
                  "checked_at": gate_checked_at},
        "assets": {"count": len(manifest), "source": asset_source, "manifest": manifest},
        # article_sha256_16 = the article's baseline hash, verified by
        # corpus_fsck.py — the one artifact the asset manifest didn't cover
        "artifacts": {"article_xml": "article.xml", "assets_dir": "assets",
                      "anzsrc_xml": "anzsrc.xml",
                      "article_sha256_16": _article_hash(out_dir)},
        # which engine built this package — rebuild_scan.py compares these against
        # pipeline_versions.PIPELINE_VERSIONS to target re-ingests at the affected
        # class after a transform fix (see CHANGELOG.md)
        "pipeline": dict(PIPELINE_VERSIONS),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if fidelity:
        # Lane-B fidelity gate verdict (lanec/pdf_fidelity.py): metrics + the largest
        # missing runs, so FLAG triage never has to re-derive what's absent.
        sc["fidelity"] = fidelity
    path = os.path.join(out_dir, NAME)
    tmp = path + ".tmp"
    json.dump(sc, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return sc
