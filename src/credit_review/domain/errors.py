"""Stable errors for callers and adapters."""


class CreditReviewError(Exception):
    code = "CREDIT_REVIEW_ERROR"


class DomainValidationError(CreditReviewError, ValueError):
    code = "INPUT_ERROR"


class AuthorizationError(CreditReviewError, PermissionError):
    code = "AUTHZ_ERROR"


class RuleExecutionError(CreditReviewError):
    code = "RULE_ERROR"


class CheckpointError(CreditReviewError):
    code = "CHECKPOINT_ERROR"


class ConflictError(CreditReviewError):
    code = "CONFLICT"
