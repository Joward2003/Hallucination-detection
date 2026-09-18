def confidence_band(*, status: str, evidence_count: int, has_conflict: bool = False, numeric_failed: bool = False) -> str:
    if has_conflict or numeric_failed or evidence_count == 0:
        return "low"
    if status == "CONTRADICTED":
        return "high"
    if status == "SUPPORTED" and evidence_count >= 2:
        return "high"
    return "medium"
