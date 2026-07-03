"""The three agent stages. Prompts are frozen module constants for cache stability."""
from job_pipeline.stages.agents.common import _fill
from job_pipeline.stages.agents.extract import EXTRACT_PROMPT, ExtractReply, ExtractStage
from job_pipeline.stages.agents.score import SCORE_PROMPT, ScoreReply, ScoreStage
from job_pipeline.stages.agents.skill_gap import (
    SKILL_GAP_PROMPT,
    SkillGapReply,
    SkillGapStage,
)

__all__ = [
    "_fill",
    "EXTRACT_PROMPT",
    "SKILL_GAP_PROMPT",
    "SCORE_PROMPT",
    "ExtractReply",
    "SkillGapReply",
    "ScoreReply",
    "ExtractStage",
    "SkillGapStage",
    "ScoreStage",
]
