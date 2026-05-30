"""Stage 5: Seed NEW lineages in under-represented domains via S2 search + GPT-5.5 grouping.

For each (domain, subfield) query, pulls top-N recent (2024-2026) cited papers from S2,
groups them by simple citation/title-similarity into candidate lineages, then writes them
as lineages/ entries with provenance=newly_built_from_s2 for downstream L1+L2+L4 to pick up.

Targets:
  biology — directed evolution, de novo protein design, AlphaFold-Multimer apps, mRNA, gene editing
  chemistry — retrosynthesis, ML for catalysis, reaction yield prediction
  materials — battery materials, photovoltaics, MOFs, alloy design
  medicine — drug discovery DL, multimodal pathology, single-cell foundation models
  physics — quantum error correction, ML for HEP, photonic computing
  earth_science — climate downscaling, ML for weather, geoscience foundation models
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    LINEAGES, POOL, LOGS, log, write_json, chat55, parse_json_block,
    parallel_map, slugify, s2_get,
)

SEEDS = {
    "biology": [
        "directed evolution protein design",
        "de novo protein design machine learning",
        "AlphaFold multimer applications",
        "mRNA vaccine design optimization",
        "CRISPR base editing therapy",
        "single-cell transcriptomics foundation model",
        "antibody design deep learning",
        "enzyme design computational",
        "protein language model pretraining",
        "RNA structure prediction deep learning",
        "synthetic biology genome editing",
        "neural cell-type embedding atlas",
        "diffusion model protein generation",
    ],
    "chemistry": [
        "retrosynthesis deep learning",
        "graph neural network catalysis",
        "reaction yield prediction transformer",
        "molecular property prediction self-supervised",
        "active learning chemistry",
        "machine learning reaction mechanism",
        "molecular dynamics neural potential",
        "DFT-trained ML potential periodic systems",
        "transition state prediction neural network",
        "inverse molecular design diffusion",
    ],
    "materials": [
        "battery materials machine learning",
        "perovskite solar cell discovery",
        "metal organic framework design",
        "high entropy alloy discovery",
        "graph neural network crystal",
        "solid-state electrolyte machine learning",
        "thermoelectric materials discovery",
        "topological materials prediction",
        "additive manufacturing process optimization",
    ],
    "medicine": [
        "drug discovery deep learning",
        "multimodal pathology foundation model",
        "clinical prediction transformer",
        "medical image segmentation foundation model",
        "ECG deep learning",
        "genomic variant classification deep learning",
        "drug-target interaction graph neural network",
        "EHR foundation model",
        "histopathology self-supervised pretraining",
    ],
    "physics": [
        "quantum error correction neural network",
        "machine learning high energy physics",
        "photonic neural network",
        "quantum optimization variational",
        "lattice QCD machine learning",
        "neural network potentials condensed matter",
        "anomaly detection LHC",
        "quantum tomography neural network",
    ],
    "earth_science": [
        "climate model machine learning downscaling",
        "weather prediction transformer",
        "geoscience foundation model",
        "atmospheric chemistry neural network",
        "GraphCast weather forecasting",
        "satellite remote sensing foundation model",
        "ocean modeling machine learning",
        "soil organic carbon deep learning",
    ],
}


def s2_search_paged(query, limit=30, year_min=2021):
    """Return list of paper dicts from S2 bulk search."""
    fields = "title,year,abstract,fieldsOfStudy,externalIds,citationCount,publicationDate,authors"
    res = s2_get("https://api.semanticscholar.org/graph/v1/paper/search",
                 {"query": query, "limit": limit, "fields": fields,
                  "year": f"{year_min}-2026"})
    out = []
    for d in res.get("data", []):
        if not d.get("title") or not d.get("year"):
            continue
        out.append({
            "paper_id": f"s2:{d['paperId']}",
            "s2_id": d["paperId"],
            "arxiv_id": (d.get("externalIds") or {}).get("ArXiv"),
            "doi": (d.get("externalIds") or {}).get("DOI"),
            "title": d["title"],
            "year": d["year"],
            "abstract": d.get("abstract") or "",
            "citation_count": d.get("citationCount") or 0,
            "fields_of_study": d.get("fieldsOfStudy") or [],
            "authors": [a.get("name") for a in d.get("authors", []) if a.get("name")],
            "publication_date": d.get("publicationDate"),
            "source_origin": "s2_seed",
        })
    return out


GROUPING_SYSTEM = """You are organizing a set of recent scientific papers into evolutionary \
lineage chains for the SciEvo-Lineage dataset.

Given a list of papers in one scientific subfield (with titles, years, abstracts), \
group them into 1-4 ordered evolutionary chains. A chain is a sequence of 4-10 papers \
where each successor builds on, refines, or extends ideas from the predecessor.

Output ONE JSON object (no markdown, no commentary):

{
  "chains": [
    {
      "chain_name": "<short descriptive name, e.g. 'Diffusion-based protein backbone generation'>",
      "subfield": "<more specific subfield label>",
      "ordered_paper_ids": ["s2:xxx", "s2:yyy", "..."]
    }
  ]
}

Rules:
1. Order papers in each chain chronologically AND by intellectual dependency.
2. Skip papers that don't fit any clear chain — better fewer well-formed chains than
   one giant mixed bag.
3. Use paper_id values EXACTLY as given.
4. Each chain must have at least 4 papers.
"""


def build_grouping_prompt(papers: list[dict], domain: str, query: str):
    parts = []
    for p in papers:
        parts.append(
            f"- paper_id: {p['paper_id']}\n"
            f"  title: {p['title']}\n"
            f"  year: {p['year']}  citations: {p['citation_count']}\n"
            f"  abstract: {(p.get('abstract') or '')[:600]}\n"
        )
    user = f"""# Domain
{domain}

# Subfield query
{query}

# Papers
{chr(10).join(parts)}

# Task
Produce the grouping JSON per system instructions.
"""
    return [
        {"role": "system", "content": GROUPING_SYSTEM},
        {"role": "user", "content": user},
    ]


def append_pool(papers: list[dict]):
    """Append new papers to the pool file (so L1 can later pick them up)."""
    pool_path = POOL / "paper_pool.jsonl"
    with open(pool_path, "a") as f:
        for p in papers:
            entry = {**p, "has_full_md": False, "parse_tool": "none",
                     "parse_dir": None, "full_md": None,
                     "domain": p.get("domain") or "cs",
                     "idea_evolving_id": None,
                     "idea_evolving_genome_card_id": None,
                     "venue": None}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_lineage(domain: str, chain_name: str, subfield: str,
                  papers: list[dict]):
    trace_id = f"trace:{domain}:{slugify(chain_name)}:s2v1"
    out_path = LINEAGES / f"{trace_id.replace(':','__')}.json"
    if out_path.exists():
        return None
    paper_ids = [p["paper_id"] for p in papers]
    lineage = {
        "trace_id": trace_id,
        "domain": domain,
        "subfield": subfield,
        "chain_name": chain_name,
        "papers": paper_ids,
        "edges": [f"edge:{paper_ids[i]}:{paper_ids[i+1]}" for i in range(len(paper_ids)-1)],
        # chain_initial_request / chain_trajectory / chain_verdict will be filled by L3 later
        "provenance": "s2_seed_v1",
        "construction": {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "stage": "05_seed_new_domains"},
        "papers_meta": [{k: p.get(k) for k in
                         ("paper_id","title","year","abstract","citation_count")}
                        for p in papers],
    }
    write_json(out_path, lineage)
    return trace_id


def process_one(args_tuple):
    domain, query = args_tuple
    papers = s2_search_paged(query, limit=20, year_min=2021)
    if len(papers) < 6:
        raise ValueError(f"too few papers for {query}: {len(papers)}")
    # Tag domain
    for p in papers:
        p["domain"] = domain

    # Append to pool (for L1 to pick up abstracts as min input)
    append_pool(papers)

    # Group via GPT-5.5
    msgs = build_grouping_prompt(papers, domain, query)
    raw = chat55(msgs, max_tokens=4000)
    obj = parse_json_block(raw)
    chains = obj.get("chains", [])
    pid_lookup = {p["paper_id"]: p for p in papers}
    created = []
    for ch in chains:
        ids = ch.get("ordered_paper_ids", [])
        chain_papers = [pid_lookup[i] for i in ids if i in pid_lookup]
        if len(chain_papers) < 4:
            continue
        tid = write_lineage(domain, ch["chain_name"], ch.get("subfield", query), chain_papers)
        if tid:
            created.append(tid)
    return {"query": query, "domain": domain, "papers": len(papers),
            "chains_kept": len(created), "chain_ids": created}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", type=str, default=None,
                    help="comma-separated subset of SEEDS keys")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    selected = SEEDS
    if args.domains:
        keep = set(args.domains.split(","))
        selected = {k: v for k, v in SEEDS.items() if k in keep}

    items = [(d, q) for d, qs in selected.items() for q in qs]
    log("seed start", n=len(items), workers=args.workers,
        domains=list(selected.keys()))

    results = parallel_map(process_one, items, max_workers=args.workers,
                           desc="seed", logfile=LOGS / "seed_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None)
    fail = sum(1 for _, r, e in results if e is not None)
    new_chains = sum((r or {}).get("chains_kept", 0) for _, r, e in results if e is None)
    new_papers = sum((r or {}).get("papers", 0) for _, r, e in results if e is None)
    log("seed done", ok=ok, fail=fail, new_chains=new_chains, new_papers_appended=new_papers)


if __name__ == "__main__":
    main()
