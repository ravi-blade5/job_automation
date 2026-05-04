import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from job_automation.job_automation.resume_tailor import (
    ResumeTailor,
    resolve_resume_tailor_file,
)


BASE_TEMPLATE = r"""\documentclass[10pt]{article}
\usepackage{resume_shared}

\begin{document}
\section{Summary}
Old summary.

\section{Professional Experience}
\RoleEntry{AI Product Manager - Enterprise AI Products}{HCLTech}{2023 -- Present}
\begin{itemize}
  \item Shaped enterprise AI roadmaps.
\end{itemize}

\section{Skills}
\SkillGroup{Old}{Old skills}

\end{document}
"""


class ResumeTailorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("g:/Antigravity/ADB_HCL/job_automation/tests/_tmp") / str(uuid4())
        self.resume_dir = self.root / "resume"
        self.latex_dir = self.resume_dir / "latex"
        self.artifacts_dir = self.root / "artifacts"
        self.latex_dir.mkdir(parents=True, exist_ok=True)
        for template_name in (
            "resume_ai_product_manager.tex",
            "resume_ai_solution_architect.tex",
            "resume_ai_consultant.tex",
        ):
            (self.latex_dir / template_name).write_text(BASE_TEMPLATE, encoding="utf-8")
        (self.latex_dir / "resume_shared.sty").write_text("% shared style", encoding="utf-8")
        (self.resume_dir / "aftermarket_ai_positioning_core.md").write_text(
            "Safe AI intervention themes and guardrails.",
            encoding="utf-8",
        )
        self.tailor = ResumeTailor(
            resume_dir=self.resume_dir,
            artifacts_dir=self.artifacts_dir,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_generates_product_manager_latex_pack(self) -> None:
        result = self.tailor.generate(
            role_title="AI Product Manager",
            company="Deloitte",
            target_track="auto",
            job_description=(
                "AI Product Manager responsible for product strategy, roadmap, GTM, "
                "RAG, prompt optimization, model evaluation, KPI ownership, and responsible AI."
            ),
        )

        self.assertEqual("ai_product_manager", result.target_track)
        self.assertIn("RAG", result.matched_keywords)
        resume_path = resolve_resume_tailor_file(
            artifacts_dir=self.artifacts_dir,
            run_id=result.run_id,
            filename="tailored_resume.tex",
        )
        tex = resume_path.read_text(encoding="utf-8")
        self.assertIn("Deloitte", tex)
        self.assertIn("Targeted JD Alignment", tex)
        self.assertIn("JD-Matched Keywords", tex)
        self.assertNotIn("Old summary.", tex)
        self.assertTrue((resume_path.parent / "cover_note_120_words.txt").is_file())
        self.assertTrue((resume_path.parent / "referral_message_3_lines.txt").is_file())
        self.assertTrue((resume_path.parent / "keyword_report.txt").is_file())
        self.assertTrue((resume_path.parent / "tailored_resume.pdf").is_file())
        self.assertIn("tailored_resume_pdf", result.files)

    def test_auto_detects_solution_architect_track(self) -> None:
        result = self.tailor.generate(
            target_track="auto",
            job_description=(
                "Solution Architect role for enterprise AI architecture, Azure cloud, "
                "API integration, microservices, security controls, and deployment readiness."
            ),
        )

        self.assertEqual("ai_solution_architect", result.target_track)

    def test_auto_detects_consultant_track(self) -> None:
        result = self.tailor.generate(
            target_track="auto",
            job_description=(
                "AI consultant needed for transformation advisory, executive workshops, "
                "stakeholder management, business case development, and operating model design."
            ),
        )

        self.assertEqual("ai_consultant", result.target_track)

    def test_rejects_short_jd(self) -> None:
        with self.assertRaises(ValueError):
            self.tailor.generate(job_description="AI PM")


if __name__ == "__main__":
    unittest.main()
