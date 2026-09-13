"""Explicit outcomes: a successful empty result is distinct from failure."""
from dataclasses import dataclass, field


@dataclass
class Failure:
    kind: str
    message: str
    sources: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    programs: list[dict] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    successful_chunks: int = 0

    @property
    def status(self):
        if self.failures:
            return "PARTIAL_SUCCESS" if self.successful_chunks else "FAILED"
        return "SUCCESS"


@dataclass
class DeliveryResult:
    delivered: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self):
        return not self.failed and not self.errors
