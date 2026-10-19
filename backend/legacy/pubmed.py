"""PubMed E-utilities 검색 (RAG의 '검색' 단계).

esearch로 논문 번호(PMID)를 찾고, efetch로 제목·초록을 가져와요.
NCBI 이용 규칙: API 키가 없으면 초당 3회까지만 요청할 수 있어서 요청 사이에 쉬어요.
https://www.ncbi.nlm.nih.gov/books/NBK25497/
"""
import asyncio
import os
import time
import xml.etree.ElementTree as ET

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = os.getenv("NCBI_API_KEY", "")
TOOL = "ongajok-hansang"
EMAIL = os.getenv("NCBI_EMAIL", "")
GAP = 0.12 if API_KEY else 0.36          # 요청 간격 (키 있으면 초당 10회, 없으면 3회)

# 근거 수준이 높은 논문(리뷰·메타분석·임상시험)을 먼저 찾고, 없으면 조건을 풀어서 다시 찾아요
STRONG = ('(review[pt] OR systematic review[pt] OR meta-analysis[pt] '
          'OR randomized controlled trial[pt])')
BASE_FILTER = 'humans[mh] AND hasabstract AND english[la]'

_lock = asyncio.Lock()
_last = 0.0
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 24 * 3600


def _params(**kw):
    p = {"db": "pubmed", "tool": TOOL, **kw}
    if EMAIL:
        p["email"] = EMAIL
    if API_KEY:
        p["api_key"] = API_KEY
    return p


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> httpx.Response:
    global _last
    async with _lock:                                   # 동시에 여러 요청이 와도 간격을 지켜요
        wait = GAP - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()
    r = await client.get(f"{BASE}/{path}", params=params, timeout=15)
    r.raise_for_status()
    return r


def build_term(ingredient_en: str, concern_en: str, strong: bool = True) -> str:
    def q(s: str) -> str:
        s = s.replace('"', "").strip()
        return f'("{s}"[MeSH Terms] OR "{s}"[tiab])'
    term = f"{q(ingredient_en)} AND {q(concern_en)} AND {BASE_FILTER}"
    return f"{term} AND {STRONG}" if strong else term


async def search(client: httpx.AsyncClient, ingredient_en: str, concern_en: str, retmax: int = 3) -> list[str]:
    """식재료 × 건강 문제로 PMID를 찾아요. 근거 수준 높은 논문이 없으면 조건을 풀어요."""
    key = f"s|{ingredient_en.lower()}|{concern_en.lower()}|{retmax}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]  # type: ignore[return-value]

    ids: list[str] = []
    for strong in (True, False):
        r = await _get(client, "esearch.fcgi", _params(
            term=build_term(ingredient_en, concern_en, strong),
            retmode="json", retmax=retmax, sort="relevance"))
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if ids:
            break
    _cache[key] = (time.time(), ids)
    return ids


def _text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


async def fetch(client: httpx.AsyncClient, pmids: list[str], max_chars: int = 1500) -> dict[str, dict]:
    """PMID 목록의 제목·저널·연도·초록을 가져와요."""
    pmids = [p for p in dict.fromkeys(pmids) if p]
    if not pmids:
        return {}
    r = await _get(client, "efetch.fcgi", _params(id=",".join(pmids), retmode="xml", rettype="abstract"))
    root = ET.fromstring(r.content)
    out: dict[str, dict] = {}
    for art in root.iter("PubmedArticle"):
        pmid = _text(art.find(".//MedlineCitation/PMID"))
        parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            t = _text(ab)
            parts.append(f"{label}: {t}" if label else t)
        abstract = " ".join(parts)
        if len(abstract) > max_chars:
            abstract = abstract[:max_chars].rsplit(" ", 1)[0] + " …"
        out[pmid] = {
            "pmid": pmid,
            "title": _text(art.find(".//ArticleTitle")),
            "journal": _text(art.find(".//Journal/Title")),
            "year": _text(art.find(".//JournalIssue/PubDate/Year")) or _text(art.find(".//JournalIssue/PubDate/MedlineDate"))[:4],
            "types": [_text(t) for t in art.findall(".//PublicationType")],
            "abstract": abstract,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
    return out
