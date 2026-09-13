from dataclasses import dataclass,field
from typing import Any


@dataclass
class SourceFailure(Exception):
    kind: str
    message: str
    retryable: bool=False
    http_status: int | None=None
    def __str__(self): return f'{self.kind}: {self.message}'


@dataclass
class Candidate:
    source: str
    source_program_id: str | None
    discovery_url: str
    official_detail_url: str
    title: str
    raw_metadata: dict = field(default_factory=dict)
    discovered_at: str | None = None


@dataclass
class AcquiredDetail:
    url: str
    text: str
    title: str
    document_urls: list[tuple[str,str]] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)
    evidence_warning: str | None = None


class SourceAdapter:
    def discover(self): raise NotImplementedError
    def fetch_detail(self,candidate): raise NotImplementedError
    def fetch_documents(self,detail): raise NotImplementedError
    def normalize(self,candidate,detail,documents): raise NotImplementedError
