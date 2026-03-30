"""Abstract base class for all dataset ingestors."""

from abc import ABC, abstractmethod
from typing import Iterator, Dict


class BaseIngestor(ABC):
    """Yields raw dicts, one per dataset example."""

    @abstractmethod
    def ingest(self) -> Iterator[Dict]:
        """Yield raw records from the source."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Human-readable source name for metadata tagging."""
        ...
