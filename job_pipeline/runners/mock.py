"""Registry exposure for the token-free mock runner."""

from job_pipeline.core.registry import register_runner
from job_pipeline.core.runner import MockRunner

register_runner("mock")(MockRunner)
