from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class WeightedKeyword:
    keyword: str
    weight: int = 1
    source: str = ""


@dataclass(frozen=True)
class SheetMatchResult:
    keyword_match_pct: int
    benchmark_match_pct: int
    matched_keywords: Sequence[str]


class SheetIntelligence:
    def __init__(
        self,
        keywords: Sequence[WeightedKeyword] | None = None,
        benchmark_jds: Sequence[str] | None = None,
    ):
        normalized: Dict[str, WeightedKeyword] = {}
        for item in keywords or []:
            keyword = _normalize_keyword(item.keyword)
            if not keyword:
                continue
            weight = max(int(item.weight or 1), 1)
            current = normalized.get(keyword)
            if current is None or weight > current.weight:
                normalized[keyword] = WeightedKeyword(
                    keyword=keyword,
                    weight=weight,
                    source=item.source,
                )

        self.keywords = tuple(
            sorted(normalized.values(), key=lambda item: (-item.weight, item.keyword))
        )
        self.total_weight = sum(item.weight for item in self.keywords)
        self.benchmark_keyword_sets = tuple(
            keyword_set
            for keyword_set in (
                self._matched_keyword_set(jd_text) for jd_text in (benchmark_jds or [])
            )
            if keyword_set
        )

    @property
    def keyword_count(self) -> int:
        return len(self.keywords)

    @property
    def benchmark_count(self) -> int:
        return len(self.benchmark_keyword_sets)

    def match(self, corpus: str) -> SheetMatchResult:
        matched_set = self._matched_keyword_set(corpus)
        if not matched_set:
            return SheetMatchResult(
                keyword_match_pct=0,
                benchmark_match_pct=0,
                matched_keywords=(),
            )

        keyword_weights = {item.keyword: item.weight for item in self.keywords}
        matched_weight = sum(keyword_weights.get(keyword, 1) for keyword in matched_set)
        # A JD hitting roughly 12% of the curated weighted bank is already
        # meaningful. Full-bank coverage would unfairly penalize focused roles.
        target_weight = max(12, round(self.total_weight * 0.12))
        keyword_match_pct = min(100, round((matched_weight / target_weight) * 100))

        benchmark_match_pct = 0
        for benchmark_set in self.benchmark_keyword_sets:
            union = matched_set | benchmark_set
            if not union:
                continue
            score = round((len(matched_set & benchmark_set) / len(union)) * 100)
            benchmark_match_pct = max(benchmark_match_pct, score)

        top_keywords = sorted(
            matched_set,
            key=lambda keyword: (-keyword_weights.get(keyword, 1), keyword),
        )[:8]
        return SheetMatchResult(
            keyword_match_pct=keyword_match_pct,
            benchmark_match_pct=benchmark_match_pct,
            matched_keywords=tuple(top_keywords),
        )

    def _matched_keyword_set(self, corpus: str) -> set[str]:
        normalized_corpus = _normalize_text(corpus)
        if not normalized_corpus:
            return set()
        corpus_tokens = set(_tokens(normalized_corpus))
        matched: set[str] = set()
        for item in self.keywords:
            if _keyword_hits(item.keyword, normalized_corpus, corpus_tokens):
                matched.add(item.keyword)
        return matched


def load_google_sheet_intelligence(
    *,
    credentials_file: Path,
    keyword_spreadsheet_id: str = "",
    jd_repository_spreadsheet_id: str = "",
    max_benchmark_jds: int = 100,
) -> SheetIntelligence:
    keyword_spreadsheet_id = keyword_spreadsheet_id.strip()
    jd_repository_spreadsheet_id = jd_repository_spreadsheet_id.strip()
    if not keyword_spreadsheet_id and not jd_repository_spreadsheet_id:
        return SheetIntelligence()
    if not credentials_file.exists():
        return SheetIntelligence()

    try:
        import gspread  # type: ignore
    except ImportError:
        return SheetIntelligence()

    client = gspread.service_account(filename=str(credentials_file))
    keywords: List[WeightedKeyword] = []
    benchmark_jds: List[str] = []

    if keyword_spreadsheet_id:
        try:
            keywords.extend(_read_keyword_workbook(client.open_by_key(keyword_spreadsheet_id)))
        except Exception:
            pass

    if jd_repository_spreadsheet_id:
        try:
            jd_workbook = client.open_by_key(jd_repository_spreadsheet_id)
            keywords.extend(_read_jd_frequency_keywords(jd_workbook))
            benchmark_jds.extend(_read_benchmark_jds(jd_workbook, max_items=max_benchmark_jds))
        except Exception:
            pass

    return SheetIntelligence(keywords=keywords, benchmark_jds=benchmark_jds)


def _read_keyword_workbook(workbook) -> List[WeightedKeyword]:
    results: List[WeightedKeyword] = []
    for sheet_name in ("Keywords", "Frequency"):
        values = _worksheet_values(workbook, sheet_name)
        results.extend(_keyword_records_from_values(values, source=f"keyword:{sheet_name}"))
    return results


def _read_jd_frequency_keywords(workbook) -> List[WeightedKeyword]:
    values = _worksheet_values(workbook, "Frequency")
    return _keyword_records_from_values(values, source="jd_frequency")


def _read_benchmark_jds(workbook, max_items: int) -> List[str]:
    values = _worksheet_values(workbook, "JD")
    header_index, header = _find_header(values, required=("jd",))
    if header_index is None:
        return []
    jd_col = _header_index(header, "jd")
    if jd_col is None:
        return []
    jds: List[str] = []
    for row in values[header_index + 1 :]:
        text = _cell(row, jd_col)
        if len(text) >= 200:
            jds.append(text)
        if len(jds) >= max_items:
            break
    return jds


def _keyword_records_from_values(values: List[List[str]], source: str) -> List[WeightedKeyword]:
    header_index, header = _find_header(values, required=("keyword",))
    if header_index is None:
        return []
    keyword_col = _header_index(header, "keyword")
    if keyword_col is None:
        return []
    frequency_col = _header_index(header, "frequency")
    include_col = _header_index(header, "y/n")

    records: List[WeightedKeyword] = []
    for row in values[header_index + 1 :]:
        keyword = _normalize_keyword(_cell(row, keyword_col))
        if not keyword:
            continue
        if include_col is not None and _cell(row, include_col).strip().lower() == "n":
            continue
        weight = _parse_weight(_cell(row, frequency_col) if frequency_col is not None else "")
        records.append(WeightedKeyword(keyword=keyword, weight=weight, source=source))
    return records


def _worksheet_values(workbook, sheet_name: str) -> List[List[str]]:
    try:
        return workbook.worksheet(sheet_name).get_all_values()
    except Exception:
        return []


def _find_header(
    values: List[List[str]],
    *,
    required: Iterable[str],
) -> tuple[int | None, List[str]]:
    required_set = {item.strip().lower() for item in required}
    for index, row in enumerate(values):
        normalized = [_normalize_header(cell) for cell in row]
        if required_set.issubset(set(normalized)):
            return index, normalized
    return None, []


def _header_index(header: List[str], name: str) -> int | None:
    normalized_name = _normalize_header(name)
    try:
        return header.index(normalized_name)
    except ValueError:
        return None


def _cell(row: List[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index]).strip()


def _parse_weight(raw: str) -> int:
    raw = raw.strip()
    if not raw:
        return 1
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return 1


def _keyword_hits(keyword: str, corpus: str, corpus_tokens: set[str]) -> bool:
    keyword_tokens = [token for token in _tokens(keyword) if token not in STOP_WORDS]
    if not keyword_tokens:
        return False
    if len(keyword_tokens) == 1:
        return keyword_tokens[0] in corpus_tokens

    if keyword in corpus:
        return True

    hit_count = sum(1 for token in keyword_tokens if token in corpus_tokens)
    required_hits = min(len(keyword_tokens), max(2, math.ceil(len(keyword_tokens) * 0.75)))
    return hit_count >= required_hits


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_keyword(value: str) -> str:
    text = _normalize_text(value)
    if not text or text in {"keyword", "keywords"}:
        return ""
    return text


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())
