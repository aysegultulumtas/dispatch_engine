"""Business-rule violations. The API layer maps these to HTTP 409."""


class DomainError(Exception):
    """Base class for every rule the domain refuses to break."""


class CapacityExceeded(DomainError):
    """Technician already holds the maximum number of jobs."""


class SkillMismatch(DomainError):
    """Technician does not have the skill the job requires."""


class InvalidTransition(DomainError):
    """Job status change is not allowed from the current state."""


class NoAvailableTechnician(DomainError):
    """No technician can take the job right now."""
