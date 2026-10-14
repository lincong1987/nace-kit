"""Typed (pydantic) questions and answers for the Drex classification API.

Questions are built by :mod:`nace_kit.presets` or directly::

    from nace_kit.types import Noul, Choice, Score

    Noul(instructions="Refund?", criteria=NoulCriteria(true="wants money back"))
    Choice(instructions="Topic?", criteria={"billing": "payments", "technical": None})
    Score(instructions="Anger?", criteria=["calm", "annoyed", "angry"])

:class:`ClassifyResult` is what :meth:`NaceClient.classify` returns — attribute
access throughout; ``.model_dump()`` for a plain dict.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _KitModel(BaseModel):
    # "model" is an API response field; opt out of pydantic's model_ namespace.
    model_config = ConfigDict(protected_namespaces=())


def _wire_excluding(d: dict, keys: tuple[str, ...]) -> dict:
    return {k: v for k, v in d.items() if k not in keys and v is not None}


class _Question(_KitModel):
    """Base for typed questions; ``name`` keys the answer and never hits the wire."""

    name: str | None = None

    def wire(self) -> dict:
        """The upstream JSON for this question, without its ``name``."""
        raise NotImplementedError


class NoulCriteria(_KitModel):
    """Optional descriptions of the yes and no outcomes."""

    true: str | None = None
    false: str | None = None


class Noul(_Question):
    """Yes/no question; the answer's ``noul`` is the probability of yes."""

    type: Literal["noul"] = "noul"
    instructions: str | None = None
    criteria: NoulCriteria | None = None

    def wire(self) -> dict:
        d = _wire_excluding(self.model_dump(mode="json"), ("name",))
        if self.criteria is not None:
            # keep explicit nulls: the API schema allows them and they mean "undescribed"
            d["criteria"] = self.criteria.model_dump(mode="json")
        return d


class Choice(_Question):
    """One label from an unordered set; ``criteria`` maps label -> description."""

    type: Literal["choice"] = "choice"
    instructions: str | None = None
    criteria: dict[str, str | None]

    def wire(self) -> dict:
        d = _wire_excluding(self.model_dump(mode="json"), ("name",))
        d["criteria"] = dict(self.criteria)  # preserve explicit nulls
        return d


class Score(_Question):
    """A place on an ordered scale; ``criteria`` lists the level labels."""

    type: Literal["score"] = "score"
    instructions: str | None = None
    criteria: list[str]

    def wire(self) -> dict:
        return _wire_excluding(self.model_dump(mode="json"), ("name",))


Question = Annotated[Union[Noul, Choice, Score], Field(discriminator="type")]


class NoulAnswer(_KitModel):
    type: Literal["noul"] = "noul"
    noul: float
    """Probability of yes, 0..1."""


class ChoiceAnswer(_KitModel):
    type: Literal["choice"] = "choice"
    choice: str
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)


class ScoreAnswer(_KitModel):
    type: Literal["score"] = "score"
    score: float
    """Expected level in the index space of the question's ``legend``."""
    confidence: float | None = None
    legend: list[str] = Field(default_factory=list)
    probabilities: dict[str, float] = Field(default_factory=dict)
    """Level indexes as string keys, e.g. ``{"0": 0.29, "1": 0.30}``."""


Answer = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer], Field(discriminator="type")]


class Usage(_KitModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelInfo(_KitModel):
    name: str
    description: str | None = None
    release_date: str | None = None
    alias_for: str | None = None
    """The version an alias such as ``drex-latest`` resolves to; ``None`` when pinned."""


class ModelsResult(_KitModel):
    models: list[ModelInfo] = Field(default_factory=list)
    latency_ms: float | None = None
    """Added by nace-kit: round trip as seen from the client."""


class ClassifyResult(_KitModel):
    """Response of :meth:`nace_kit.NaceClient.classify`."""

    model: str
    answers: dict[str, Answer] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    evaluation_time_ms: float | None = None
    request_id: str | None = None
    latency_ms: float | None = None
    """Added by nace-kit: round trip as seen from the client."""
