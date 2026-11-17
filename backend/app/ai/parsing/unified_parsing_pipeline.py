"""Compatibility entrypoint for the current section-grounded parser."""
from app.ai.parsing.lightweight_parser_v8 import (
    LightweightParsingError as UnifiedParsingError,
    LightweightParsingPipelineV8 as UnifiedParsingPipeline,
)
