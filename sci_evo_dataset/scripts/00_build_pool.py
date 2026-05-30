"""Build paper_pool.jsonl — unified candidate index across yqh parses + IdeaEvolving paper_db + S2 metadata.

Output: _pool/paper_pool.jsonl  (one paper per line)
Each entry: paper_id, s2_id, arxiv_id, title, year, abstract, fields_of_study,
            domain (heuristic), parse_tool, parse_dir, has_full_md
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    YQH, YQH_PARSE_MAPS, YQH_ALL_PAPERS, IDEA_PAPER_DB, POOL,
    log, make_paper_id, write_json, jsonl_append, read_json,
)


CS_KEYWORDS = ["Computer Science", "Artificial Intelligence", "Machine Learning"]
BIO_KEYWORDS = ["Biology", "Bioinformatics", "Genetics", "Molecular Biology", "Biochemistry"]
CHEM_KEYWORDS = ["Chemistry", "Chemical Engineering"]
MAT_KEYWORDS = ["Materials Science"]
MED_KEYWORDS = ["Medicine", "Pharmacology", "Pathology", "Oncology"]
PHYS_KEYWORDS = ["Physics", "Quantum Physics", "Photonics"]
EARTH_KEYWORDS = ["Geology", "Geosciences", "Climate", "Earth Sciences", "Oceanography", "Atmospheric Science"]


def classify_domain(fields: list[str]) -> str:
    """Single best-fit domain string for routing extraction prompts."""
    if not fields:
        return "cs"  # default
    f_set = set(fields)
    for kws, name in [
        (BIO_KEYWORDS, "biology"),
        (CHEM_KEYWORDS, "chemistry"),
        (MAT_KEYWORDS, "materials"),
        (MED_KEYWORDS, "medicine"),
        (PHYS_KEYWORDS, "physics"),
        (EARTH_KEYWORDS, "earth_science"),
        (CS_KEYWORDS, "cs"),
    ]:
        if any(k in f_set for k in kws):
            return name
    return "cs"


def main():
    POOL.mkdir(parents=True, exist_ok=True)
    out_path = POOL / "paper_pool.jsonl"
    if out_path.exists():
        out_path.unlink()

    log("loading yqh all_papers.json (S2 metadata)")
    s2_meta = json.loads(YQH_ALL_PAPERS.read_text())
    log("s2 metadata records", n=len(s2_meta))

    log("loading parse mappings")
    parse_index: dict[str, dict] = {}
    for pm_path in YQH_PARSE_MAPS:
        if not pm_path.exists():
            continue
        pm = json.loads(pm_path.read_text())
        # tag tool
        if "docling" in pm_path.name:
            tool = "docling"
        elif "batch" in pm_path.name:
            tool = "mineru_pipeline"
        else:
            tool = "mineru_cloud"
        for s2_id, info in pm.items():
            # keep FIRST mapping (priority: cloud > batch > docling order if we iterate mineru first)
            if s2_id in parse_index:
                continue
            parse_index[s2_id] = {
                "parse_tool": tool,
                "parse_dir": str(YQH / info["parse_dir"]),
                "full_md": str(YQH / info["full_md"]),
                "pdf_filename": info.get("pdf_filename", ""),
                "source": info.get("source", "unknown"),
            }
    # Prioritize MinerU: re-loop with order
    parse_index_pref: dict[str, dict] = {}
    for tool_priority, pm_path in [("mineru_cloud", YQH_PARSE_MAPS[0]),
                                    ("mineru_pipeline", YQH_PARSE_MAPS[1]),
                                    ("docling", YQH_PARSE_MAPS[2])]:
        if not pm_path.exists():
            continue
        pm = json.loads(pm_path.read_text())
        for s2_id, info in pm.items():
            if s2_id in parse_index_pref:
                continue
            parse_index_pref[s2_id] = {
                "parse_tool": tool_priority,
                "parse_dir": str(YQH / info["parse_dir"]),
                "full_md": str(YQH / info["full_md"]),
                "pdf_filename": info.get("pdf_filename", ""),
                "source": info.get("source", "unknown"),
            }
    parse_index = parse_index_pref
    log("parsed papers indexed", n=len(parse_index),
        mineru_cloud=sum(1 for v in parse_index.values() if v["parse_tool"]=="mineru_cloud"),
        mineru_pipeline=sum(1 for v in parse_index.values() if v["parse_tool"]=="mineru_pipeline"),
        docling=sum(1 for v in parse_index.values() if v["parse_tool"]=="docling"))

    log("loading IdeaEvolving paper_db")
    idea_db = json.loads(IDEA_PAPER_DB.read_text())
    log("IdeaEvolving papers", n=len(idea_db))

    # Build index by s2_id and by title-slug for IdeaEvolving cross-link
    idea_by_s2: dict[str, dict] = {}
    idea_by_title: dict[str, dict] = {}
    for pid, rec in idea_db.items():
        if rec.get("s2_id"):
            idea_by_s2[rec["s2_id"]] = rec
        if rec.get("title"):
            t = rec["title"].lower().strip()
            idea_by_title[t] = rec

    # Build pool: union of (S2-known papers from yqh) ∪ IdeaEvolving papers
    seen = set()
    domains = {}
    parsed_count = {"mineru_cloud":0, "mineru_pipeline":0, "docling":0, "none":0}

    # 1) From yqh s2_meta + parse_index
    for s2_id, meta in s2_meta.items():
        if s2_id in seen:
            continue
        seen.add(s2_id)
        title = meta.get("title") or ""
        year = meta.get("year")
        fields = meta.get("fieldsOfStudy") or []
        domain = classify_domain(fields)
        pinfo = parse_index.get(s2_id, {})
        parsed_count[pinfo.get("parse_tool", "none")] += 1
        domains[domain] = domains.get(domain, 0) + 1
        # Cross-link IdeaEvolving id if title matches
        ie = idea_by_s2.get(s2_id) or idea_by_title.get(title.lower().strip())
        paper_id = (ie or {}).get("paper_id") or make_paper_id(title, year)
        entry = {
            "paper_id": paper_id,
            "s2_id": s2_id,
            "arxiv_id": (meta.get("externalIds") or {}).get("ArXiv") or (meta.get("externalIds") or {}).get("arXiv"),
            "doi": (meta.get("externalIds") or {}).get("DOI"),
            "title": title,
            "year": year,
            "venue": meta.get("venue"),
            "abstract": meta.get("abstract") or "",
            "citation_count": meta.get("citationCount") or 0,
            "fields_of_study": fields,
            "domain": domain,
            "authors": [a.get("name") for a in meta.get("authors", []) if a.get("name")],
            "publication_date": meta.get("publicationDate"),
            "parse_tool": pinfo.get("parse_tool", "none"),
            "parse_dir": pinfo.get("parse_dir"),
            "full_md": pinfo.get("full_md"),
            "has_full_md": bool(pinfo.get("full_md")),
            "source_origin": "yqh_s2",
            "idea_evolving_id": (ie or {}).get("paper_id") if ie else None,
            "idea_evolving_genome_card_id": (ie or {}).get("genome_card_id") if ie else None,
        }
        jsonl_append(out_path, entry)

    # 2) From IdeaEvolving paper_db entries NOT in yqh (mostly have only abstract)
    added_ie = 0
    for pid, rec in idea_db.items():
        s2_id = rec.get("s2_id") or ""
        if s2_id and s2_id in seen:
            continue
        title = rec.get("title") or ""
        if title.lower().strip() in idea_by_title and not s2_id:
            pass  # ok, original
        year = rec.get("year")
        fields = rec.get("fields_of_study") or []
        domain = classify_domain(fields) if fields else "cs"
        domains[domain] = domains.get(domain, 0) + 1
        entry = {
            "paper_id": pid,
            "s2_id": s2_id or None,
            "arxiv_id": None,
            "doi": None,
            "title": title,
            "year": year,
            "venue": rec.get("venue"),
            "abstract": rec.get("abstract") or "",
            "citation_count": 0,
            "fields_of_study": fields,
            "domain": domain,
            "authors": rec.get("authors") or [],
            "publication_date": None,
            "parse_tool": "none",
            "parse_dir": None,
            "full_md": None,
            "has_full_md": False,
            "source_origin": "ideaevolving_db",
            "idea_evolving_id": pid,
            "idea_evolving_genome_card_id": rec.get("genome_card_id"),
        }
        jsonl_append(out_path, entry)
        added_ie += 1

    summary = {
        "total_in_pool": sum(domains.values()),
        "yqh_added": len(s2_meta),
        "ie_added": added_ie,
        "domains": domains,
        "parsed_breakdown": parsed_count,
        "output_path": str(out_path),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json(POOL / "pool_summary.json", summary)
    log("done", **summary)


if __name__ == "__main__":
    main()
