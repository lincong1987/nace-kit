"""Question builders for the nace.ai Drex SystemOne API.

All three upstream question types (verified against the live API and the
official nace-sdk source, 2026-10-14):

- ``noul``   -> binary question, returns ``{"noul": 0.0..1.0}`` (probability
  of yes); optional ``criteria`` descriptions sharpen what yes/no mean.
- ``choice`` -> one label from an unordered set, ``criteria`` is a mapping
  ``{label: description}``; returns ``choice`` + per-label probabilities.
- ``score``  -> position on an ordered scale, ``criteria`` is the list of
  level labels; returns continuous ``score`` + per-level probabilities +
  ``confidence``.

Up to 512 questions can be batched into a single request; ``state`` may be
any JSON value, not just text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Question = dict[str, Any]


def noul(
    question: str,
    *,
    name: str = "answer",
    true: str | None = None,
    false: str | None = None,
) -> Question:
    """Binary question scored 0..1 (e.g. "Does this convey urgency?").

    ``true``/``false`` optionally describe what each outcome means, which
    sharpens calibration. The returned ``noul`` is the probability of yes.
    """
    q: Question = {"name": name, "type": "noul", "instructions": question}
    if true is not None or false is not None:
        q["criteria"] = {
            "true": true,
            "false": false,
        }
    return q


def choice(
    question: str,
    options: Mapping[str, str | None],
    *,
    name: str = "answer",
) -> Question:
    """Single-label classification over an unordered set of ``options``.

    ``options`` maps each label to a short description (or ``None``), e.g.
    ``{"billing": "payments, payouts, invoices", "technical": "bugs, outages"}``.
    Returns the chosen ``choice``, per-label ``probabilities`` and
    ``confidence``.
    """
    return {
        "name": name,
        "type": "choice",
        "instructions": question,
        "criteria": dict(options),
    }


def score(question: str, levels: list[str], *, name: str = "answer") -> Question:
    """Rated question over ordered ``levels`` (e.g. calm/annoyed/angry/furious).

    Returns a continuous ``score`` (index space of the levels), per-level
    ``probabilities`` and a ``confidence`` value.
    """
    return {
        "name": name,
        "type": "score",
        "instructions": question,
        "criteria": list(levels),
    }


def urgency(*, name: str = "is_urgent") -> Question:
    """Preset: does the text convey urgency?"""
    return noul("Does this convey urgency?", name=name)


def sentiment(*, name: str = "sentiment") -> Question:
    """Preset: overall sentiment as negative / neutral / positive."""
    return score(
        "What is the overall sentiment of this text?",
        ["negative", "neutral", "positive"],
        name=name,
    )


def severity(*, name: str = "severity") -> Question:
    """Preset: issue severity from minor to critical."""
    return score(
        "How severe is the issue described?",
        ["minor", "moderate", "major", "critical"],
        name=name,
    )


def priority(*, name: str = "priority") -> Question:
    """Preset: triage priority as a choice over low/medium/high/urgent."""
    return choice(
        "What priority should this get?",
        {
            "low": "no rush, handle whenever",
            "medium": "handle soon, not blocking",
            "high": "should be handled today",
            "urgent": "drop everything, someone is blocked or losing money",
        },
        name=name,
    )
