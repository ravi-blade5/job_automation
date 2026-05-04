from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .models import (
    Decision,
    FitScoreRecord,
    JobIngestRecord,
    RoleTrack,
    SeniorityMatch,
)
from .enrichment.sheet_intelligence import SheetIntelligence


@dataclass(frozen=True)
class CandidateProfile:
    title_keywords: Sequence[str]
    must_have_keywords: Sequence[str]
    domain_keywords: Sequence[str]
    tool_keywords: Sequence[str]


AI_PM_PROFILE = CandidateProfile(
    title_keywords=(
        "ai product manager",
        "genai product manager",
        "enterprise ai product",
        "technical product manager",
        "product manager",
        "product owner",
        "product lead",
        "ai platform",
        "ai strategy",
        "presales",
    ),
    must_have_keywords=(
        "product vision",
        "product strategy",
        "roadmap",
        "customer discovery",
        "executive workshop",
        "product-market fit",
        "go-to-market",
        "gtm",
        "stakeholder",
        "agile",
        "kpi",
        "partner ecosystem",
        "enterprise ai",
    ),
    domain_keywords=(
        "telecom",
        "media",
        "financial services",
        "automotive",
        "support workflows",
        "operations",
        "ams",
        "sdlc",
        "value stream mapping",
        "transformation",
    ),
    tool_keywords=(
        "jira",
        "power bi",
        "azure",
        "azure marketplace",
        "python",
        "openai",
        "vertex ai",
    ),
)

GENAI_LEAD_PROFILE = CandidateProfile(
    title_keywords=(
        "ai solution expert",
        "genai solution expert",
        "genai solutions lead",
        "ai solutions lead",
        "solutions expert",
        "solutions consultant",
        "solution architect",
        "customer engineer",
        "sales engineer",
        "technical consultant",
        "enterprise ai",
        "genai",
        "ai platform",
        "presales",
        "ai strategy",
        "solutions consultant",
        "technical product manager",
    ),
    must_have_keywords=(
        "solution design",
        "solutioning",
        "genai",
        "llm",
        "rag",
        "prompt engineering",
        "ai governance",
        "model deployment",
        "evaluation",
        "solution architecture",
        "technical discovery",
        "customer workshop",
        "executive workshop",
        "value articulation",
        "demo",
        "enterprise ai",
        "operating model",
        "customer discovery",
    ),
    domain_keywords=(
        "enterprise ai",
        "support workflows",
        "workflow automation",
        "value stream mapping",
        "automation",
        "responsible ai",
        "sdlc",
        "transformation",
        "proposal",
    ),
    tool_keywords=(
        "openai api",
        "vertex ai",
        "azure openai",
        "python",
        "azure",
        "aws bedrock",
        "azure marketplace",
        "promptops",
        "power bi",
        "salesforce",
        "servicenow",
        "iso 27001",
    ),
)


class FitScorer:
    def __init__(
        self,
        must_apply_threshold: int = 80,
        good_fit_threshold: int = 65,
        company_focus_keywords: Sequence[str] | None = None,
        company_focus_bonus: int = 12,
        sheet_intelligence: SheetIntelligence | None = None,
        resume_profile_keywords: Sequence[str] | None = None,
    ):
        self.must_apply_threshold = must_apply_threshold
        self.good_fit_threshold = good_fit_threshold
        self.company_focus_keywords = [
            item.strip().lower() for item in (company_focus_keywords or []) if item.strip()
        ]
        self.company_focus_bonus = company_focus_bonus
        self.sheet_intelligence = sheet_intelligence
        self.resume_profile_keywords = [
            item.strip().lower()
            for item in (resume_profile_keywords or [])
            if item.strip()
        ][:80]

    def score(self, job: JobIngestRecord, role_track: RoleTrack) -> FitScoreRecord:
        profile = AI_PM_PROFILE if role_track == RoleTrack.AI_PM else GENAI_LEAD_PROFILE
        corpus = f"{job.title_raw} {job.description_text}".lower()
        title_corpus = job.title_raw.lower()
        company_corpus = f"{job.company} {job.job_url}".lower()

        title_match = max(
            _match_pct(title_corpus, profile.title_keywords),
            _title_alignment(title_corpus, role_track),
        )
        must_have = _match_pct(corpus, profile.must_have_keywords)
        domain = _match_pct(corpus, profile.domain_keywords)
        tools = _match_pct(corpus, profile.tool_keywords)
        if not job.description_text.strip() and title_match >= 80:
            must_have = max(must_have, 45)
        if role_track == RoleTrack.GENAI_LEAD and any(
            token in title_corpus
            for token in (
                "ai solution expert",
                "genai solution expert",
                "solutions expert",
                "solutions consultant",
                "solution consultant",
                "customer engineer",
                "sales engineer",
                "technical consultant",
            )
        ):
            must_have = max(must_have, 50)
            domain = max(domain, 35)
        seniority = _seniority_match(corpus)
        seniority_score = {
            SeniorityMatch.HIGH: 100,
            SeniorityMatch.MEDIUM: 70,
            SeniorityMatch.LOW: 40,
        }[seniority]
        company_focus_hit = any(keyword in company_corpus for keyword in self.company_focus_keywords)
        company_focus_score = self.company_focus_bonus if company_focus_hit else 0
        sheet_match = self.sheet_intelligence.match(corpus) if self.sheet_intelligence else None
        sheet_score = 0
        if sheet_match:
            sheet_score = min(
                15,
                round(sheet_match.keyword_match_pct * 0.10)
                + round(sheet_match.benchmark_match_pct * 0.05),
            )
        resume_match = _match_pct(corpus, self.resume_profile_keywords)
        resume_matched_terms = _matched_terms(corpus, self.resume_profile_keywords, limit=6)
        resume_score = min(18, round(resume_match * 0.18))

        fit_score = min(
            100,
            round(
                (0.30 * title_match)
                + (0.30 * must_have)
                + (0.15 * domain)
                + (0.15 * tools)
                + (0.10 * seniority_score)
                + company_focus_score
                + sheet_score
                + resume_score
            ),
        )
        decision = _decision_for(
            fit_score=fit_score,
            must_have_match_pct=max(must_have, title_match),
            must_apply_threshold=self.must_apply_threshold,
            good_fit_threshold=self.good_fit_threshold,
        )
        reason_codes = _reason_codes(
            title_match,
            must_have,
            domain,
            tools,
            seniority,
            decision,
            company_focus_hit,
            sheet_match,
            resume_match,
            resume_matched_terms,
        )

        return FitScoreRecord(
            job_id=job.job_id,
            role_track=role_track,
            fit_score=fit_score,
            must_have_match_pct=must_have,
            domain_match_pct=domain,
            seniority_match=seniority,
            decision=decision,
            reason_codes=reason_codes,
        )


def _match_pct(corpus: str, keywords: Iterable[str]) -> int:
    normalized = [item.strip().lower() for item in keywords if item.strip()]
    if not normalized:
        return 0
    hit = sum(1 for keyword in normalized if keyword in corpus)
    return round((hit / len(normalized)) * 100)


def _matched_terms(corpus: str, keywords: Iterable[str], *, limit: int) -> List[str]:
    normalized = []
    seen = set()
    for item in keywords:
        keyword = item.strip().lower()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        normalized.append(keyword)
    return [keyword for keyword in normalized if keyword in corpus][:limit]


def _seniority_match(corpus: str) -> SeniorityMatch:
    if any(token in corpus for token in ("principal", "director", "head of", "staff", "lead", "senior")):
        return SeniorityMatch.HIGH
    if any(token in corpus for token in ("manager", "owner", "consultant", "specialist")):
        return SeniorityMatch.MEDIUM
    return SeniorityMatch.LOW


def _title_alignment(title: str, role_track: RoleTrack) -> int:
    normalized = title.strip().lower()
    if not normalized:
        return 0

    if role_track == RoleTrack.AI_PM:
        if "technical product manager" in normalized and any(
            token in normalized for token in ("ai", "genai", "ml", "machine learning", "platform")
        ):
            return 95
        if "product manager" in normalized and any(
            token in normalized for token in ("ai", "genai", "ml", "machine learning", "platform", "enterprise")
        ):
            return 100
        if any(token in normalized for token in ("product owner", "product lead")) and any(
            token in normalized for token in ("ai", "genai", "platform")
        ):
            return 82
        if "presales" in normalized and "ai" in normalized:
            return 70
        if "product manager" in normalized:
            return 62
        return 0

    if "genai" in normalized and any(
        token in normalized for token in ("lead", "manager", "architect", "strategy")
    ):
        return 100
    if any(token in normalized for token in ("ai solution expert", "genai solution expert", "solutions expert")):
        return 98
    if "ai solutions" in normalized and any(
        token in normalized for token in ("lead", "architect", "consultant", "manager")
    ):
        return 96
    if any(token in normalized for token in ("solutions consultant", "solution consultant")) and any(
        token in normalized for token in ("ai", "genai", "enterprise")
    ):
        return 94
    if any(token in normalized for token in ("customer engineer", "sales engineer", "technical consultant")) and any(
        token in normalized for token in ("ai", "genai", "enterprise")
    ):
        return 92
    if "solution architect" in normalized and any(
        token in normalized for token in ("ai", "genai")
    ):
        return 94
    if any(token in normalized for token in ("enterprise ai", "ai platform")) and any(
        token in normalized for token in ("lead", "manager", "architect")
    ):
        return 86
    if "presales" in normalized and "ai" in normalized:
        return 72
    if "genai" in normalized or "enterprise ai" in normalized:
        return 60
    return 0


def _decision_for(
    fit_score: int,
    must_have_match_pct: int,
    must_apply_threshold: int,
    good_fit_threshold: int,
) -> Decision:
    if fit_score >= must_apply_threshold and must_have_match_pct >= 50:
        return Decision.MUST_APPLY
    if fit_score >= good_fit_threshold:
        return Decision.GOOD_FIT
    return Decision.LOW_FIT


def _reason_codes(
    title_match: int,
    must_have: int,
    domain: int,
    tools: int,
    seniority: SeniorityMatch,
    decision: Decision,
    company_focus_hit: bool,
    sheet_match=None,
    resume_match: int = 0,
    resume_matched_terms: Sequence[str] | None = None,
) -> List[str]:
    reasons: List[str] = []
    if title_match >= 45:
        reasons.append("strong_title_alignment")
    if must_have >= 60:
        reasons.append("strong_must_have_alignment")
    if domain >= 40:
        reasons.append("strong_domain_alignment")
    if tools >= 35:
        reasons.append("strong_tool_alignment")
    if seniority == SeniorityMatch.HIGH:
        reasons.append("strong_seniority_match")
    if company_focus_hit:
        reasons.append("preferred_company_match")
    if sheet_match and sheet_match.keyword_match_pct >= 30:
        keywords = "|".join(list(sheet_match.matched_keywords)[:5])
        reasons.append(f"curated_keyword_match:{keywords}" if keywords else "curated_keyword_match")
    if sheet_match and sheet_match.benchmark_match_pct >= 25:
        reasons.append("benchmark_jd_similarity")
    if resume_match > 0:
        reasons.append(f"resume_profile_match:{resume_match}pct")
    if resume_matched_terms:
        reasons.append(f"resume_keywords:{'|'.join(resume_matched_terms[:5])}")
    if must_have < 35:
        reasons.append("must_have_gap")
    if decision == Decision.LOW_FIT:
        reasons.append("below_fit_threshold")
    return reasons
