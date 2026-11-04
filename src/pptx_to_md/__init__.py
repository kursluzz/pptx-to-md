"""Convert PowerPoint (.pptx) decks to Markdown, with optional LLM image and slide descriptions."""

from importlib.metadata import PackageNotFoundError, version

from .config import ConfigError, Settings, load_settings
from .converter import convert_file, convert_tree
from .extract import extract_presentation
from .llm import LLMDescriber

try:
    __version__ = version("pptx-to-md")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0+unknown"

__all__ = [
    "ConfigError",
    "LLMDescriber",
    "Settings",
    "convert_file",
    "convert_tree",
    "extract_presentation",
    "load_settings",
]
