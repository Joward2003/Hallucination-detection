from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_retrieval_attempts: int = 2

    def can_rewrite(self, attempt: int, evidence_status: str) -> bool:
        return evidence_status == "INSUFFICIENT" and attempt < self.max_retrieval_attempts - 1
