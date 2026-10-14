"""Tests for the typed question/answer layer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nace_kit.types import (
    Choice,
    ChoiceAnswer,
    ClassifyResult,
    Noul,
    NoulCriteria,
    Score,
    ScoreAnswer,
)
from nace_kit.client import normalize_questions
from nace_kit import presets


class TestQuestionWire:
    def test_noul_wire_strips_name_keeps_criteria_nulls(self):
        q = Noul(name="wants_refund", instructions="Refund?",
                 criteria=NoulCriteria(true="wants money back", false=None))
        assert q.wire() == {
            "type": "noul",
            "instructions": "Refund?",
            "criteria": {"true": "wants money back", "false": None},
        }

    def test_noul_without_criteria(self):
        assert presets.urgency().wire() == {
            "type": "noul", "instructions": "Does this convey urgency?",
        }

    def test_choice_wire_preserves_label_nulls(self):
        q = Choice(name="cat", instructions="What?",
                   criteria={"billing": "payments", "technical": None})
        assert q.wire()["criteria"] == {"billing": "payments", "technical": None}

    def test_score_wire(self):
        q = Score(name="mood", instructions="How angry?", criteria=["calm", "angry"])
        assert q.wire() == {
            "type": "score", "instructions": "How angry?", "criteria": ["calm", "angry"],
        }

    def test_discriminated_union_parses_answers(self):
        result = ClassifyResult.model_validate({
            "model": "drex-latest",
            "answers": {
                "u": {"type": "noul", "noul": 0.7161},
                "c": {"type": "choice", "choice": "billing", "confidence": 0.85,
                      "probabilities": {"billing": 0.9, "technical": 0.05}},
                "s": {"type": "score", "score": 1.31, "confidence": 0.7,
                      "legend": ["calm", "angry"], "probabilities": {"0": 0.2, "1": 0.8}},
            },
            "usage": {"input_tokens": 26, "output_tokens": 24},
            "evaluation_time_ms": 122.6,
            "request_id": "req_x",
            "latency_ms": 150.0,
        })
        assert result.answers["u"].noul == 0.7161
        assert result.answers["c"].choice == "billing"
        assert result.answers["s"].probabilities["1"] == 0.8
        # model field must not trip pydantic's model_ namespace
        assert result.model == "drex-latest"
        dumped = result.model_dump(mode="json")
        assert dumped["answers"]["c"]["choice"] == "billing"

    def test_bad_answer_type_rejected(self):
        with pytest.raises(ValidationError):
            ClassifyResult.model_validate({
                "model": "drex-latest",
                "answers": {"x": {"type": "choice", "choice": 3}},
            })


class TestNormalizeAcceptsTyped:
    def test_single_model(self):
        assert normalize_questions(presets.urgency()) == {
            "is_urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
        }

    def test_mixed_list(self):
        out = normalize_questions([presets.urgency(), {"name": "raw", "type": "noul", "instructions": "r"}])
        assert set(out) == {"is_urgent", "raw"}
        assert out["is_urgent"]["instructions"] == "Does this convey urgency?"
        assert out["raw"]["instructions"] == "r"

    def test_mapping_of_models(self):
        out = normalize_questions({"a": presets.urgency()})
        assert out["a"]["type"] == "noul"

    def test_dict_form_still_works(self):
        out = normalize_questions({"a": {"type": "noul", "instructions": "x"}})
        assert out == {"a": {"type": "noul", "instructions": "x"}}
