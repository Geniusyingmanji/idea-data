"""Stage 7 — fixed: 4-step MinerU Cloud Precision API flow.

  step 1: download PDF from openAccessPdf URL or arxiv
  step 2: POST /file-urls/batch  → get presigned upload URLs + batch_id
  step 3: PUT pdf bytes to each presigned URL
  step 4: GET /extract-results/batch/{batch_id}  until each result state == done
  step 5: download full_zip_url, extract full.md + content_list.json
  step 6: append the new paper to paper_pool.jsonl with parse_tool=mineru_cloud
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request, urllib.error
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    LINEAGES, POOL, LOGS, log, jsonl_iter, jsonl_append, s2_get,
)

MINERU_TOKEN = "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIzNDYwMDg2OCIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NTE5MjA4NSwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiIiwib3BlbklkIjpudWxsLCJ1dWlkIjoiOWRhZGUzMTItNGU1MS00MjE5LTljYmQtNzE2N2NjN2I5MTU5IiwiZW1haWwiOiIiLCJleHAiOjE3OTI0NzIwODV9.4hZLul2qRTn9QI748A27uAOCYyJzx0y3ur-PIThRIzLMB-cH4yRdNd-SvVmVwbyH2_1uePBgyte6N0XbXwqRvA"
SUBMIT_URL = "https://mineru.net/api/v4/file-urls/batch"
QUERY_URL = "https://mineru.net/api/v4/extract-results/batch/{batch_id}"
HEADERS = {"Authorization": f"Bearer {MINERU_TOKEN}"}

MINERU_NEW = POOL / "mineru_new"
MINERU_NEW.mkdir(parents=True, exist_ok=True)
PDF_CACHE = POOL / "pdf_cache"
PDF_CACHE.mkdir(parents=True, exist_ok=True)


def http_get_bytes(url: str, timeout=120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SciEvo/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_put_bytes(url: str, body: bytes, timeout=300):
    req = urllib.request.Request(url, data=body, method="PUT")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def http_json(url, method, headers, payload=None, timeout=120):
    body = None
    h = dict(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_s2_pdf_url(s2_id: str) -> str | None:
    """Prefer arxiv > biorxiv > openAccessPdf (less prone to publisher 403s)."""
    try:
        r = s2_get(f"https://api.semanticscholar.org/graph/v1/paper/{s2_id}",
                   {"fields": "openAccessPdf,externalIds"})
        ext = r.get("externalIds") or {}
        arx = ext.get("ArXiv") or ext.get("arXiv")
        if arx:
            return f"https://arxiv.org/pdf/{arx}.pdf"
        oap = (r.get("openAccessPdf") or {}).get("url") or ""
        # Skip known publisher walls
        if oap and not any(b in oap for b in (
            "ieeexplore.ieee.org", "link.springer.com", "doi.org",
            "academic.oup.com", "onlinelibrary.wiley.com",
            "sciencedirect.com", "nature.com",
        )):
            return oap
        # Biorxiv fallback if DOI is biorxiv
        doi = ext.get("DOI") or ""
        if doi and "biorxiv" in doi.lower():
            return f"https://www.biorxiv.org/content/{doi}.full.pdf"
    except Exception as e:
        log("s2 pdf lookup failed", id=s2_id, err=str(e)[:200])
    return None


def collect_new_papers(limit=None):
    seen = set()
    pool_seen = set()
    for d in MINERU_NEW.iterdir():
        if d.is_dir() and (d / "full.md").exists():
            pool_seen.add(d.name)

    out = []
    for p in LINEAGES.glob("*.json"):
        try:
            obj = json.loads(p.read_text())
        except Exception:
            continue
        if obj.get("provenance") != "s2_seed_v1":
            continue
        for pm in obj.get("papers_meta", []):
            pid = pm.get("paper_id")
            if not pid:
                continue
            safe = pid.replace(":", "__").replace("/", "_")
            if safe in pool_seen or pid in seen:
                continue
            seen.add(pid)
            out.append({**pm, "safe_id": safe})
            if limit and len(out) >= limit:
                return out
    return out


def step1_download(papers):
    """Download PDFs to PDF_CACHE. Returns list of papers with local pdf_path."""
    ok = []
    for p in papers:
        pid = p["paper_id"]
        safe = p["safe_id"]
        cached = PDF_CACHE / f"{safe}.pdf"
        if cached.exists() and cached.stat().st_size > 1000:
            p["pdf_path"] = str(cached)
            ok.append(p)
            continue
        s2 = pid.replace("s2:", "")
        url = fetch_s2_pdf_url(s2)
        if not url:
            continue
        try:
            data = http_get_bytes(url, timeout=120)
            if len(data) < 1000 or not data[:4] == b"%PDF":
                # likely an HTML error page; skip
                continue
            cached.write_bytes(data)
            p["pdf_path"] = str(cached)
            ok.append(p)
        except Exception as e:
            log("pdf download fail", pid=pid, err=str(e)[:120])
    return ok


def step2_submit_batch(papers):
    """Submit batch, return (batch_id, file_urls list parallel to papers)."""
    payload = {
        "enable_formula": True,
        "language": "en",
        "enable_table": True,
        "model_version": "pipeline",
        "files": [{"name": Path(p["pdf_path"]).name,
                   "data_id": p["paper_id"]} for p in papers],
    }
    res = http_json(SUBMIT_URL, "POST", HEADERS, payload)
    if res.get("code") != 0:
        raise RuntimeError(f"submit error: {res}")
    return res["data"]["batch_id"], res["data"]["file_urls"]


def step3_upload(papers, file_urls):
    """Upload each PDF to its presigned URL."""
    ok = 0
    for p, url in zip(papers, file_urls):
        try:
            body = Path(p["pdf_path"]).read_bytes()
            status = http_put_bytes(url, body, timeout=300)
            if status in (200, 201, 204):
                ok += 1
        except Exception as e:
            log("pdf upload fail", pid=p["paper_id"], err=str(e)[:120])
    return ok


def step4_poll(batch_id, timeout=1800, interval=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            res = http_json(QUERY_URL.format(batch_id=batch_id), "GET", HEADERS, timeout=60)
            if res.get("code") != 0:
                raise RuntimeError(f"poll error: {res}")
            results = res["data"]["extract_result"]
            if all(r.get("state") in ("done", "failed") for r in results):
                return results
        except Exception as e:
            log("poll exception (will retry)", err=str(e)[:120])
        time.sleep(interval)
    raise TimeoutError(f"batch {batch_id} did not finish in {timeout}s")


def step5_extract(results, papers_by_pid):
    """Download zip + extract full.md."""
    saved = 0
    for r in results:
        pid = r.get("data_id")
        if r.get("state") != "done":
            log("file failed", pid=pid, err=r.get("err_msg", "?"))
            continue
        zip_url = r.get("full_zip_url")
        if not zip_url:
            continue
        try:
            zip_bytes = http_get_bytes(zip_url, timeout=300)
            safe = papers_by_pid[pid]["safe_id"]
            target = MINERU_NEW / safe
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                for name in z.namelist():
                    if name.endswith(".md"):
                        (target / "full.md").write_bytes(z.read(name))
                    elif "content_list" in name and name.endswith(".json"):
                        (target / "content_list.json").write_bytes(z.read(name))
            if (target / "full.md").exists():
                meta = papers_by_pid[pid]
                entry = {
                    "paper_id": pid,
                    "s2_id": pid.replace("s2:", ""),
                    "arxiv_id": None,
                    "doi": None,
                    "title": meta.get("title", ""),
                    "year": meta.get("year"),
                    "venue": None,
                    "abstract": meta.get("abstract", ""),
                    "citation_count": meta.get("citation_count", 0),
                    "fields_of_study": [],
                    "domain": meta.get("domain", "cross_domain"),
                    "authors": [],
                    "publication_date": None,
                    "parse_tool": "mineru_cloud",
                    "parse_dir": str(target),
                    "full_md": str(target / "full.md"),
                    "has_full_md": True,
                    "source_origin": "s2_seed_mineru",
                    "idea_evolving_id": None,
                    "idea_evolving_genome_card_id": None,
                }
                jsonl_append(POOL / "paper_pool.jsonl", entry)
                saved += 1
        except Exception as e:
            log("zip handle fail", pid=pid, err=str(e)[:120])
    return saved


def process_batch(papers):
    """Single full 5-step run for a batch of papers (up to ~20 per call)."""
    if not papers:
        return 0
    log(f"step 1: downloading {len(papers)} PDFs")
    papers = step1_download(papers)
    if not papers:
        log("no PDFs downloaded")
        return 0
    log(f"step 2: submitting batch for {len(papers)} papers")
    batch_id, file_urls = step2_submit_batch(papers)
    log("submitted", batch_id=batch_id)
    log("step 3: uploading PDFs")
    n_up = step3_upload(papers, file_urls)
    log("uploads", ok=n_up, total=len(papers))
    log("step 4: polling")
    results = step4_poll(batch_id)
    states = {}
    for r in results:
        states[r.get("state")] = states.get(r.get("state"), 0) + 1
    log("poll done", states=states)
    by_pid = {p["paper_id"]: p for p in papers}
    log("step 5: extracting")
    saved = step5_extract(results, by_pid)
    log("saved", n=saved)
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=15)
    ap.add_argument("--max-batches", type=int, default=4)
    args = ap.parse_args()

    new = collect_new_papers(limit=args.max)
    log("new candidates", n=len(new))
    saved_total = 0
    for i in range(0, min(len(new), args.batch_size * args.max_batches), args.batch_size):
        batch = new[i: i + args.batch_size]
        try:
            saved_total += process_batch(batch)
        except Exception as e:
            log("batch failed", err=str(e)[:300])
            time.sleep(10)
    log("mineru session done", attempted=len(new), saved=saved_total)


if __name__ == "__main__":
    main()
