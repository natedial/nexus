"""reMarkable cloud capture adapter."""

from research_gleaner.remarkable.client import RemarkableDocument, RemarkableLibrary
from research_gleaner.remarkable.extractor import extract_document

__all__ = ["RemarkableDocument", "RemarkableLibrary", "extract_document"]
