"""Provider-neutral final host context for model bridges."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SloBridgeCancellationReason = Literal["user_abort", "stop_hook", "shutdown", "host_failure"]


class SloBridgeSessionOptionsDAO(BaseModel):
    """Immutable host context supplied after normal Slo prompt assembly."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: str = Field(min_length=1, max_length=256, description="Owning host session ID.")
    working_directory: Path = Field(description="Absolute host working directory.")
    instructions: str = Field(description="Complete final host-authored instructions.")

    @field_validator("working_directory")
    @classmethod
    def validate_absolute_directory(cls, value: Path) -> Path:
        """Reject relative configuration without performing filesystem I/O."""
        if not value.is_absolute():
            raise ValueError("Bridge working directory must be absolute.")
        return value
