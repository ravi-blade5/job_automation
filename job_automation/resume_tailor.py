from __future__ import annotations

import json
import mimetypes
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from uuid import uuid4


@dataclass(frozen=True)
class TrackConfig:
    key: str
    label: str
    template_name: str
    points_name: str
    summary_role: str
    classification_terms: Tuple[str, ...]
    core_skills: Tuple[str, ...]
    delivery_skills: Tuple[str, ...]


@dataclass(frozen=True)
class ResumeTailorResult:
    run_id: str
    target_track: str
    track_label: str
    role_title: str
    company: str
    matched_keywords: List[str]
    confidence: float
    files: Dict[str, Dict[str, str]]
    summary_preview: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "target_track": self.target_track,
            "track_label": self.track_label,
            "role_title": self.role_title,
            "company": self.company,
            "matched_keywords": self.matched_keywords,
            "confidence": self.confidence,
            "files": self.files,
            "summary_preview": self.summary_preview,
        }


TRACKS: Dict[str, TrackConfig] = {
    "ai_product_manager": TrackConfig(
        key="ai_product_manager",
        label="AI Product Manager",
        template_name="resume_ai_product_manager.tex",
        points_name="resume_points_ai_product_manager_aftermarket_cloud.md",
        summary_role="AI Product Manager",
        classification_terms=(
            "product manager",
            "product owner",
            "roadmap",
            "product strategy",
            "gtm",
            "go-to-market",
            "kpi",
            "okr",
            "adoption",
            "launch",
            "pricing",
            "user story",
            "prd",
            "backlog",
            "0 to 1",
            "customer discovery",
        ),
        core_skills=(
            "AI Product Management",
            "Product Strategy",
            "Roadmapping",
            "0 to 1 Product Development",
            "KPI Ownership",
            "GTM Strategy",
            "Pilot Success Definition",
        ),
        delivery_skills=(
            "Value Stream Mapping",
            "Partner Onboarding",
            "A/B Testing",
            "User Journey Design",
            "LLM Cost Governance",
            "Cross-Functional Execution",
        ),
    ),
    "ai_solution_architect": TrackConfig(
        key="ai_solution_architect",
        label="AI Solution Architect",
        template_name="resume_ai_solution_architect.tex",
        points_name="resume_points_ai_solution_architect_aftermarket_cloud.md",
        summary_role="AI Solution Architect",
        classification_terms=(
            "solution architect",
            "solutions architect",
            "architecture",
            "reference architecture",
            "cloud architecture",
            "azure",
            "aws",
            "integration",
            "api",
            "security",
            "deployment",
            "microservices",
            "technical discovery",
            "pre-sales",
            "presales",
        ),
        core_skills=(
            "AI Solution Architecture",
            "Enterprise Architecture",
            "Systems Integration",
            "Cloud Architecture",
            "API-Led Integration",
            "Implementation Readiness",
            "Technical Discovery",
        ),
        delivery_skills=(
            "Governance Controls",
            "Reference Architecture",
            "Microservices Integration",
            "Security Readiness",
            "Partner Technical Evaluation",
            "Deployment Constraints",
        ),
    ),
    "ai_consultant": TrackConfig(
        key="ai_consultant",
        label="AI Consultant",
        template_name="resume_ai_consultant.tex",
        points_name="resume_points_ai_consultant_aftermarket_cloud.md",
        summary_role="AI Consultant",
        classification_terms=(
            "consultant",
            "consulting",
            "advisory",
            "transformation",
            "workshop",
            "stakeholder",
            "business case",
            "operating model",
            "change management",
            "strategy",
            "assessment",
            "discovery",
        ),
        core_skills=(
            "AI Consulting",
            "Enterprise AI Strategy",
            "Transformation Advisory",
            "Use-Case Discovery",
            "Workshop Facilitation",
            "Business Case Development",
            "Stakeholder Alignment",
        ),
        delivery_skills=(
            "Value Stream Mapping",
            "Change Enablement",
            "Governance-Aware Adoption",
            "Pilot Advisory",
            "Executive Narrative Building",
            "Solutioning",
        ),
    ),
}


KEYWORD_CATALOG: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Agentic AI", ("agentic", "agent", "multi-agent", "autonomous agent")),
    ("GenAI", ("genai", "generative ai", "llm", "large language model")),
    ("RAG", ("rag", "retrieval augmented", "retrieval-augmented", "knowledge search")),
    ("Prompt Optimization", ("prompt", "prompt engineering", "prompt optimization")),
    ("Model Evaluation", ("model evaluation", "eval", "evaluation", "bert score", "f1", "bleu", "topic adherence")),
    ("Responsible AI", ("responsible ai", "governance", "guardrail", "risk", "compliance")),
    ("Product Strategy", ("product strategy", "roadmap", "prioritization", "product roadmap")),
    ("GTM", ("gtm", "go-to-market", "commercialization", "launch")),
    ("0 to 1", ("0 to 1", "zero to one", "new product", "greenfield")),
    ("Enterprise SaaS", ("enterprise saas", "saas", "platform", "multi-tenant")),
    ("Workflow Automation", ("workflow", "automation", "orchestration", "process automation")),
    ("Cloud Architecture", ("cloud", "azure", "aws", "gcp", "cloud run")),
    ("API Integration", ("api", "integration", "connector", "microservice", "microservices")),
    ("Stakeholder Management", ("stakeholder", "cross-functional", "executive", "customer workshop")),
    ("KPI Ownership", ("kpi", "okr", "metric", "success metric", "business outcome")),
    ("Partner Ecosystem", ("partner", "partnership", "ecosystem", "pilot account", "poc")),
    ("RFP Automation", ("rfp", "proposal", "bid", "response automation")),
    ("LLM Cost Governance", ("cost", "token", "rerun", "latency", "optimization")),
    ("Data Privacy", ("pii", "redaction", "privacy", "data protection")),
    ("A/B Testing", ("a/b", "ab test", "experimentation", "test and learn")),
)


class ResumeTailor:
    def __init__(
        self,
        *,
        resume_dir: Path,
        artifacts_dir: Path,
        gcs_bucket: str = "",
        gcs_prefix: str = "artifacts",
        gcp_project_id: str = "",
    ) -> None:
        self.resume_dir = resume_dir
        self.artifacts_root = artifacts_dir / "resume_tailor"
        self.gcs_bucket = gcs_bucket.strip().removeprefix("gs://").rstrip("/")
        self.gcs_prefix = gcs_prefix.strip().strip("/") or "artifacts"
        self.gcp_project_id = gcp_project_id.strip()
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        *,
        job_description: str,
        target_track: str = "auto",
        role_title: str = "",
        company: str = "",
    ) -> ResumeTailorResult:
        jd_text = _normalize_space(job_description)
        if len(jd_text) < 40:
            raise ValueError("Paste a fuller JD first. I need at least 40 characters.")

        role_title = _normalize_space(role_title) or _infer_role_title(jd_text)
        company = _normalize_space(company)
        track, confidence = self._select_track(jd_text, target_track, role_title)
        template_path = self.resume_dir / "latex" / track.template_name
        if not template_path.is_file():
            raise FileNotFoundError(f"Resume template not found: {template_path}")

        matched_keywords = _matched_keywords(" ".join([role_title, company, jd_text]))
        context_text = self._load_context(track)
        tailored_summary = _build_summary(
            track=track,
            role_title=role_title,
            company=company,
            matched_keywords=matched_keywords,
        )
        alignment_line = _build_alignment_line(matched_keywords)
        tailored_latex = self._tailor_latex(
            template_path.read_text(encoding="utf-8"),
            track=track,
            summary=tailored_summary,
            alignment_line=alignment_line,
            matched_keywords=matched_keywords,
        )

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        output_dir = self.artifacts_root / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "tailored_resume": output_dir / "tailored_resume.tex",
            "tailored_resume_pdf": output_dir / "tailored_resume.pdf",
            "cover_note": output_dir / "cover_note_120_words.txt",
            "referral_message": output_dir / "referral_message_3_lines.txt",
            "keyword_report": output_dir / "keyword_report.txt",
            "job_description": output_dir / "job_description.txt",
            "metadata": output_dir / "metadata.json",
        }
        files["tailored_resume"].write_text(tailored_latex, encoding="utf-8")
        _write_resume_pdf(
            latex_source=tailored_latex,
            output_path=files["tailored_resume_pdf"],
            track_label=track.label,
            role_title=role_title,
            company=company,
        )
        files["cover_note"].write_text(
            _build_cover_note(track, role_title, company, matched_keywords),
            encoding="utf-8",
        )
        files["referral_message"].write_text(
            _build_referral_message(track, role_title, company),
            encoding="utf-8",
        )
        files["keyword_report"].write_text(
            _build_keyword_report(
                track=track,
                confidence=confidence,
                matched_keywords=matched_keywords,
                context_text=context_text,
            ),
            encoding="utf-8",
        )
        files["job_description"].write_text(jd_text, encoding="utf-8")
        files["metadata"].write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "target_track": track.key,
                    "track_label": track.label,
                    "role_title": role_title,
                    "company": company,
                    "matched_keywords": matched_keywords,
                    "confidence": confidence,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        shared_style = self.resume_dir / "latex" / "resume_shared.sty"
        if shared_style.is_file():
            shutil.copy2(shared_style, output_dir / "resume_shared.sty")

        gcs_uris = self._mirror_to_gcs(run_id, files)
        result_files = {
            label: {
                "filename": path.name,
                "url": f"/files/resume-tailor/{run_id}/{path.name}",
                "gcs_uri": gcs_uris.get(label, ""),
            }
            for label, path in files.items()
        }

        return ResumeTailorResult(
            run_id=run_id,
            target_track=track.key,
            track_label=track.label,
            role_title=role_title,
            company=company,
            matched_keywords=matched_keywords,
            confidence=confidence,
            files=result_files,
            summary_preview=tailored_summary,
        )

    def _select_track(
        self,
        jd_text: str,
        target_track: str,
        role_title: str,
    ) -> Tuple[TrackConfig, float]:
        normalized = target_track.strip().lower()
        if normalized in TRACKS:
            return TRACKS[normalized], 1.0
        if normalized and normalized != "auto":
            raise ValueError(
                f"Unsupported target_track '{target_track}'. Choose auto, "
                f"{', '.join(TRACKS)}."
            )

        haystack = f"{role_title} {jd_text}".lower()
        scores = {
            key: sum(1 for term in track.classification_terms if term in haystack)
            for key, track in TRACKS.items()
        }
        selected_key = max(scores, key=scores.get)
        total = sum(scores.values())
        if total == 0:
            selected_key = "ai_product_manager"
            confidence = 0.34
        else:
            confidence = round(scores[selected_key] / total, 2)
        return TRACKS[selected_key], confidence

    def _load_context(self, track: TrackConfig) -> str:
        snippets = []
        for name in ("aftermarket_ai_positioning_core.md", track.points_name):
            path = self.resume_dir / name
            if path.is_file():
                snippets.append(path.read_text(encoding="utf-8", errors="ignore"))
        return "\n\n".join(snippets)

    def _tailor_latex(
        self,
        source: str,
        *,
        track: TrackConfig,
        summary: str,
        alignment_line: str,
        matched_keywords: List[str],
    ) -> str:
        escaped_summary = _latex_escape(summary)
        escaped_alignment = _latex_escape(alignment_line)
        summary_block = (
            "\\section{Summary}\n"
            f"{escaped_summary}\n\n"
            "\\MiniHeading{Targeted JD Alignment}\n"
            f"\\InlineSectionText{{{escaped_alignment}}}\n\n"
            "\\section{Professional Experience}"
        )
        tailored = re.sub(
            r"\\section\{Summary\}.*?\\section\{Professional Experience\}",
            lambda _match: summary_block,
            source,
            count=1,
            flags=re.DOTALL,
        )
        if tailored == source:
            raise ValueError("Could not locate Summary and Professional Experience sections in template.")

        skills_block = _build_skills_section(track, matched_keywords)
        tailored = re.sub(
            r"\\section\{Skills\}.*?\\end\{document\}",
            lambda _match: skills_block + "\n\n\\end{document}",
            tailored,
            count=1,
            flags=re.DOTALL,
        )
        return tailored

    def _mirror_to_gcs(self, run_id: str, files: Dict[str, Path]) -> Dict[str, str]:
        if not self.gcs_bucket:
            return {}
        try:
            from google.cloud import storage  # type: ignore
        except Exception:
            return {}

        client = storage.Client(project=self.gcp_project_id or None)
        bucket = client.bucket(self.gcs_bucket)
        uploaded = {}
        for label, path in files.items():
            if not path.exists():
                continue
            blob_name = f"{self.gcs_prefix}/resume_tailor/{run_id}/{path.name}"
            blob = bucket.blob(blob_name)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            blob.upload_from_filename(str(path), content_type=content_type)
            uploaded[label] = f"gs://{self.gcs_bucket}/{blob_name}"
        return uploaded


def resolve_resume_tailor_file(
    *,
    artifacts_dir: Path,
    run_id: str,
    filename: str,
    gcs_bucket: str = "",
    gcs_prefix: str = "artifacts",
    gcp_project_id: str = "",
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise PermissionError("Invalid resume-tailor run id.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise PermissionError("Invalid resume-tailor file name.")

    root = (artifacts_dir / "resume_tailor").resolve()
    path = (root / run_id / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Resume-tailor file path is outside the allowed artifact root.") from exc

    if path.is_file():
        return path

    bucket_name = gcs_bucket.strip().removeprefix("gs://").rstrip("/")
    if bucket_name:
        _download_resume_tailor_file_from_gcs(
            path=path,
            bucket_name=bucket_name,
            blob_name=f"{gcs_prefix.strip().strip('/') or 'artifacts'}/resume_tailor/{run_id}/{filename}",
            project_id=gcp_project_id,
        )
        if path.is_file():
            return path

    raise FileNotFoundError(f"Resume-tailor file not found: {filename}")


def _download_resume_tailor_file_from_gcs(
    *,
    path: Path,
    bucket_name: str,
    blob_name: str,
    project_id: str,
) -> None:
    try:
        from google.cloud import storage  # type: ignore
    except Exception as exc:
        raise FileNotFoundError("GCS fallback unavailable because google-cloud-storage is not installed.") from exc
    client = storage.Client(project=project_id or None)
    blob = client.bucket(bucket_name).blob(blob_name)
    if not blob.exists(client):
        raise FileNotFoundError(f"GCS artifact not found: gs://{bucket_name}/{blob_name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(path))


def _matched_keywords(text: str) -> List[str]:
    normalized = text.lower()
    matches = []
    for label, aliases in KEYWORD_CATALOG:
        if any(alias in normalized for alias in aliases):
            matches.append(label)
    return matches[:14]


def _build_summary(
    *,
    track: TrackConfig,
    role_title: str,
    company: str,
    matched_keywords: List[str],
) -> str:
    target = role_title or track.label
    if company:
        target = f"{target} at {company}"
    signals = _join_keywords(matched_keywords[:8]) or "enterprise AI, GenAI, roadmap definition, governance, and measurable delivery"
    if track.key == "ai_solution_architect":
        return (
            f"{track.summary_role} with 7+ years translating product, customer, and platform requirements into "
            f"enterprise-ready AI solution patterns for {target}. Strong fit for JD priorities across {signals}, "
            "with experience in agentic workflows, RAG, integrations, validation gates, partner technical evaluation, "
            "and governance-aware deployment narratives."
        )
    if track.key == "ai_consultant":
        return (
            f"{track.summary_role} with 7+ years advising enterprise teams on AI-led workflow transformation for {target}. "
            f"Strong fit for JD priorities across {signals}, with experience in discovery, value stream mapping, use-case "
            "prioritization, business-case framing, partner pilots, and responsible AI adoption planning."
        )
    return (
        f"{track.summary_role} with 7+ years across enterprise SaaS and AI products, tailored for {target}. "
        f"Strong fit for JD priorities across {signals}, with experience spanning ideation, build, MVP, evaluations, "
        "optimization, scale, agentic RFP automation, AI roadmap definition, partner pilots, and KPI-backed product execution."
    )


def _build_alignment_line(matched_keywords: List[str]) -> str:
    if matched_keywords:
        return f"Matched priorities: {_join_keywords(matched_keywords)}."
    return (
        "Matched priorities: enterprise AI product strategy, governance-aware GenAI adoption, "
        "cross-functional execution, and measurable workflow transformation."
    )


def _build_skills_section(track: TrackConfig, matched_keywords: List[str]) -> str:
    lines = ["\\section{Skills}"]
    if matched_keywords:
        lines.append(
            f"\\SkillGroup{{JD-Matched Keywords}}{{{_latex_escape(_join_keywords(matched_keywords[:12]))}}}"
        )
    lines.append(
        f"\\SkillGroup{{Core Role Fit}}{{{_latex_escape(_join_keywords(track.core_skills))}}}"
    )
    lines.append(
        f"\\SkillGroup{{Enterprise AI}}{{{_latex_escape('GenAI Strategy, RAG, Agentic Workflow Design, Prompt Optimization, Model Evaluation, Responsible AI, LLM Cost Governance')}}}"
    )
    lines.append(
        f"\\SkillGroup{{Execution Methods}}{{{_latex_escape(_join_keywords(track.delivery_skills))}}}"
    )
    return "\n".join(lines)


def _build_cover_note(
    track: TrackConfig,
    role_title: str,
    company: str,
    matched_keywords: List[str],
) -> str:
    target = role_title or track.label
    company_text = f" at {company}" if company else ""
    signals = _join_keywords(matched_keywords[:5]) or "enterprise AI, GenAI, product strategy, governance, and measurable execution"
    text = (
        f"I am interested in the {target}{company_text} role. My background combines {track.label.lower()} work across "
        f"enterprise SaaS, GenAI workflows, and AI-enabled transformation. The JD appears aligned to {signals}. "
        "I bring practical experience in moving AI ideas from discovery to MVP, evaluation, optimization, and scale, "
        "including RAG setup, model-output checks, partner pilots, agentic RFP automation, and governance-aware rollout. "
        "I would value the opportunity to discuss how I can contribute to the team."
    )
    return _trim_to_words(text, 120)


def _build_referral_message(track: TrackConfig, role_title: str, company: str) -> str:
    target = role_title or track.label
    company_text = f" at {company}" if company else ""
    return "\n".join(
        [
            f"Hi, I am exploring the {target}{company_text} role and saw a strong fit with my enterprise AI background.",
            f"I bring {track.label.lower()} experience across GenAI roadmaps, RAG/evaluation, agentic workflows, and governance-aware rollout.",
            "If relevant, I would appreciate a referral or guidance on the right hiring contact.",
        ]
    )


def _build_keyword_report(
    *,
    track: TrackConfig,
    confidence: float,
    matched_keywords: List[str],
    context_text: str,
) -> str:
    safe_context_hint = "Available" if context_text.strip() else "Not found"
    return "\n".join(
        [
            f"Selected track: {track.label}",
            f"Classification confidence: {confidence}",
            f"Matched JD keywords: {_join_keywords(matched_keywords) or 'None detected'}",
            f"Resume context files: {safe_context_hint}",
            "",
            "How to use this:",
            "- Review the generated LaTeX before submitting.",
            "- Keep the stronger claims only if you can defend them in interview.",
            "- Use the keyword list to decide whether the role is worth a manual application.",
        ]
    )


def _infer_role_title(jd_text: str) -> str:
    for line in jd_text.splitlines():
        cleaned = _normalize_space(line)
        if 6 <= len(cleaned) <= 90 and not cleaned.endswith("."):
            return cleaned
    return ""


def _join_keywords(values: Iterable[str]) -> str:
    return ", ".join(value for value in values if value)


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _trim_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip()


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _write_resume_pdf(
    *,
    latex_source: str,
    output_path: Path,
    track_label: str,
    role_title: str,
    company: str,
) -> None:
    try:
        from reportlab.lib import colors  # type: ignore
        from reportlab.lib.enums import TA_CENTER  # type: ignore
        from reportlab.lib.pagesizes import letter  # type: ignore
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
        from reportlab.lib.units import inch  # type: ignore
        from reportlab.platypus import (  # type: ignore
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except Exception as exc:
        raise RuntimeError("PDF generation requires reportlab. Install dependencies from requirements.txt.") from exc

    parsed = _parse_latex_resume(latex_source)
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "ResumeName",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        spaceAfter=2,
        textColor=colors.black,
    )
    contact_style = ParagraphStyle(
        "Contact",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=8.6,
        leading=10,
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=12,
        spaceBefore=5,
        spaceAfter=3,
        borderWidth=0,
        borderColor=colors.black,
        borderPadding=0,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=8.6,
        leading=10.4,
        spaceAfter=3,
    )
    role_style = ParagraphStyle(
        "Role",
        parent=body_style,
        fontName="Helvetica-Bold",
        spaceBefore=2,
    )
    mini_style = ParagraphStyle(
        "Mini",
        parent=body_style,
        fontName="Helvetica-Bold",
        spaceBefore=2,
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=body_style,
        leftIndent=8,
        firstLineIndent=0,
        spaceAfter=1.5,
    )

    story = [
        Paragraph(_pdf_escape(parsed.get("name") or "Sri Ravi Kumar Birada"), name_style),
        Paragraph(_pdf_escape(parsed.get("contact") or ""), contact_style),
    ]
    target = " | ".join(part for part in (role_title, company, track_label) if part)
    if target:
        story.append(Paragraph(_pdf_escape(target), contact_style))

    for block in parsed["blocks"]:
        kind = block["kind"]
        text = str(block["text"])
        if kind == "section":
            story.append(Paragraph(_pdf_escape(text), section_style))
        elif kind == "role":
            story.append(Paragraph(_pdf_escape(text), role_style))
        elif kind == "mini":
            story.append(Paragraph(_pdf_escape(text), mini_style))
        elif kind == "bullet_group":
            items = [
                ListItem(Paragraph(_pdf_escape(item), bullet_style), leftIndent=8)
                for item in block["items"]
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="circle",
                    leftIndent=12,
                    bulletFontSize=5,
                )
            )
        elif text.strip():
            story.append(Paragraph(_pdf_escape(text), body_style))
        story.append(Spacer(1, 1.5))

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.42 * inch,
        leftMargin=0.42 * inch,
        topMargin=0.36 * inch,
        bottomMargin=0.36 * inch,
        title=f"{track_label} Resume",
        author="Sri Ravi Kumar Birada",
    )
    document.build(story)


def _parse_latex_resume(latex_source: str) -> Dict[str, object]:
    name_match = re.search(r"\\ResumeName\{([^}]*)\}", latex_source)
    contact_match = re.search(r"\\ResumeContact\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", latex_source)
    parsed: Dict[str, object] = {
        "name": _latex_to_text(name_match.group(1)) if name_match else "",
        "contact": " | ".join(_latex_to_text(part) for part in contact_match.groups()) if contact_match else "",
        "blocks": [],
    }
    blocks: List[Dict[str, object]] = parsed["blocks"]  # type: ignore[assignment]
    bullet_buffer: List[str] = []

    def flush_bullets() -> None:
        if bullet_buffer:
            blocks.append({"kind": "bullet_group", "text": "", "items": list(bullet_buffer)})
            bullet_buffer.clear()

    skip_prefixes = (
        "\\documentclass",
        "\\usepackage",
        "\\begin{document}",
        "\\end{document}",
        "\\fontsize",
        "\\begin{itemize}",
        "\\end{itemize}",
        "\\ResumeName",
        "\\ResumeContact",
    )
    for raw_line in latex_source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or any(line.startswith(prefix) for prefix in skip_prefixes):
            continue
        section = re.match(r"\\section\{(.+)\}", line)
        if section:
            flush_bullets()
            blocks.append({"kind": "section", "text": _latex_to_text(section.group(1))})
            continue
        role = re.match(r"\\RoleEntry\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", line)
        if role:
            flush_bullets()
            title, org, dates = (_latex_to_text(part) for part in role.groups())
            blocks.append({"kind": "role", "text": f"{title} | {org} | {dates}"})
            continue
        mini = re.match(r"\\MiniHeading\{(.+)\}", line)
        if mini:
            flush_bullets()
            blocks.append({"kind": "mini", "text": _latex_to_text(mini.group(1))})
            continue
        inline = re.match(r"\\InlineSectionText\{(.+)\}", line)
        if inline:
            flush_bullets()
            blocks.append({"kind": "text", "text": _latex_to_text(inline.group(1))})
            continue
        skill = re.match(r"\\SkillGroup\{([^}]*)\}\{(.+)\}", line)
        if skill:
            flush_bullets()
            group, values = (_latex_to_text(part) for part in skill.groups())
            blocks.append({"kind": "text", "text": f"{group}: {values}"})
            continue
        if line.startswith("\\item"):
            bullet_buffer.append(_latex_to_text(line.removeprefix("\\item").strip()))
            continue
        flush_bullets()
        blocks.append({"kind": "text", "text": _latex_to_text(line)})
    flush_bullets()
    return parsed


def _latex_to_text(value: str) -> str:
    text = str(value)
    replacements = {
        r"\&": "&",
        r"\%": "%",
        r"\$": "$",
        r"\#": "#",
        r"\_": "_",
        r"\{": "{",
        r"\}": "}",
        r"\textbar": "|",
        r"\textbackslash{}": "\\",
        r"\textasciitilde{}": "~",
        r"\textasciicircum{}": "^",
    }
    for latex, plain in replacements.items():
        text = text.replace(latex, plain)
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^]]*\])?", "", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _pdf_escape(value: str) -> str:
    return html_escape(_latex_to_text(value))


def html_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
