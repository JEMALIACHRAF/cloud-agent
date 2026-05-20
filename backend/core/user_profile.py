"""
User profiling — automatic expertise detection and response adaptation.
Detects level from vocabulary, adapts system prompts and response format.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Literal

UserLevel = Literal["beginner", "intermediate", "architect", "cto"]

# ── Keyword signals per level ─────────────────────────────────────────────────

_BEGINNER_SIGNALS = [
    r"\bwhat is\b", r"\bwhat are\b", r"\bhow do i\b", r"\bhow does\b",
    r"\bi'm new\b", r"\bi am new\b", r"\bnever used\b", r"\bjust started\b",
    r"\bdon't understand\b", r"\bexplain\b.*\bsimple\b", r"\bbeginners?\b",
    r"\bfirst time\b", r"\bhelp me start\b", r"\bwhere do i start\b",
]

_ARCHITECT_SIGNALS = [
    r"\bvpc peering\b", r"\btransit gateway\b", r"\bprivatelink\b",
    r"\bscp\b", r"\borganizations\b", r"\blanding zone\b", r"\bcontrol tower\b",
    r"\brpo\b", r"\brto\b", r"\bmulti.?region\b", r"\bdr strategy\b",
    r"\bwell.?architected\b", r"\bservice quota\b", r"\bsavings plan\b",
    r"\breserved instance\b", r"\bspot fleet\b", r"\bkapacity\b",
    r"\bcross.?account\b", r"\biam role\b.*\bassume\b", r"\bfinops\b",
    r"\bservice mesh\b", r"\benvoy\b", r"\bistio\b",
]

_CTO_SIGNALS = [
    r"\btco\b", r"\btotal cost of ownership\b", r"\bboard\b", r"\bceo\b",
    r"\bbusiness case\b", r"\broi\b", r"\bmake.or.buy\b", r"\bbuild vs buy\b",
    r"\bcompliance\b.*\bsoc\b", r"\bgdpr\b", r"\bhipaa\b", r"\bpci\b",
    r"\borganizational\b", r"\bteam.+skill\b", r"\bexecutive\b",
    r"\bstrategic\b", r"\bmigration strategy\b", r"\bcloud adoption\b",
]


def detect_level_from_text(text: str) -> UserLevel:
    """Heuristic level detection from a single message."""
    text_lower = text.lower()

    cto_score = sum(1 for p in _CTO_SIGNALS if re.search(p, text_lower))
    arch_score = sum(1 for p in _ARCHITECT_SIGNALS if re.search(p, text_lower))
    beg_score = sum(1 for p in _BEGINNER_SIGNALS if re.search(p, text_lower))

    if cto_score >= 2:
        return "cto"
    if arch_score >= 2:
        return "architect"
    if beg_score >= 1:
        return "beginner"
    return "intermediate"


# ── Per-level system prompt addendum ─────────────────────────────────────────

LEVEL_ADDENDUMS: dict[UserLevel, str] = {
    "beginner": """
## RESPONSE STYLE — BEGINNER MODE
The user is new to AWS. Apply these rules strictly:
- Start with a 1-sentence plain-English summary of what you're about to explain
- Use analogies for every AWS service: "S3 is like Google Drive but for developers"
- Spell out every acronym on first use: "IAM (Identity and Access Management)"
- After technical content, add a "🎯 What this means for you:" section in plain language
- Include estimated cost in everyday terms: "less than a coffee per month"
- End with: "📚 Next step: [one specific thing to learn or try]"
- Avoid architectural jargon unless explained
- Keep responses focused — don't overwhelm with options
""",
    "intermediate": """
## RESPONSE STYLE — INTERMEDIATE MODE
The user has AWS basics. Apply these rules:
- Use AWS service names directly, no need to explain basics
- Focus on architecture patterns and trade-offs
- Include relevant IaC snippets (CloudFormation YAML or Terraform HCL)
- Mention key limits and quotas that matter for this use case
- Show cost implications with rough estimates
- Reference AWS best practices and Well-Architected pillars where relevant
""",
    "architect": """
## RESPONSE STYLE — SENIOR ARCHITECT MODE
The user is an experienced AWS architect. Apply these rules:
- Full technical depth expected — SLAs, replication factors, consistency models
- Reference specific service limits and quotas (not just defaults)
- Compare RI vs Savings Plans vs Spot for cost optimization
- Include HA/DR considerations: RPO/RTO targets, cross-region replication
- Reference Well-Architected Framework pillars explicitly
- Compare with GCP/Azure equivalents where relevant
- Include security posture: shared responsibility specifics, IAM least-privilege patterns
- Show FinOps angles: idle resource detection, right-sizing signals
""",
    "cto": """
## RESPONSE STYLE — C-LEVEL / CTO MODE
The user is a decision-maker. Apply these rules STRICTLY:

Structure your response ALWAYS as:
### 🎯 Executive Summary
- **Business impact**: [quantified, e.g., "reduces infra cost by 40%"]
- **Risk level**: [Low/Medium/High] — [one-line reason]
- **Recommended action**: [one clear sentence]

### Technical Architecture
[technical depth — be precise]

### 💰 3-Year Total Cost of Ownership
| | Year 1 | Year 2 | Year 3 |
|---|---|---|---|
| Infrastructure | $X | $X | $X |
| Team/Operations | $X | $X | $X |
| **Total** | **$X** | **$X** | **$X** |

### ⚠️ Risks & Mitigations
| Risk | Probability | Impact | Mitigation |
|---|---|---|---|

### 🏗️ Build vs Buy vs Managed
[Direct recommendation with reasoning — no hedging]

### Compliance & Governance
[Relevant for SOC2/GDPR/HIPAA/PCI if applicable]
""",
}


@dataclass
class UserProfile:
    """Persistent user profile — accumulated across conversation turns."""
    level: UserLevel = "intermediate"
    level_confidence: int = 0          # 0-3, confirmed after N signals
    domains_of_interest: list[str] = field(default_factory=list)
    question_count: int = 0
    detected_from_messages: list[str] = field(default_factory=list)

    def update_from_message(self, message: str) -> None:
        """Update level from a new message, with growing confidence."""
        self.question_count += 1
        detected = detect_level_from_text(message)
        self.detected_from_messages.append(detected)

        # Majority vote over last 5 messages
        recent = self.detected_from_messages[-5:]
        counts: dict[str, int] = {}
        for d in recent:
            counts[d] = counts.get(d, 0) + 1
        majority = max(counts, key=counts.get)  # type: ignore
        self.level = majority  # type: ignore
        self.level_confidence = min(counts[majority], 3)

    def get_system_addendum(self) -> str:
        return LEVEL_ADDENDUMS[self.level]

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "confidence": self.level_confidence,
            "question_count": self.question_count,
        }


# Thread-local profile store (in-memory — keyed by thread_id)
_profiles: dict[str, UserProfile] = {}


def get_profile(thread_id: str) -> UserProfile:
    if thread_id not in _profiles:
        _profiles[thread_id] = UserProfile()
    return _profiles[thread_id]


def update_profile(thread_id: str, message: str) -> UserProfile:
    profile = get_profile(thread_id)
    profile.update_from_message(message)
    return profile
