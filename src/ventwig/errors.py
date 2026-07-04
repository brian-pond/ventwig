class VentwigError(Exception):
    pass


class ConfigError(VentwigError):
    pass


class LockError(VentwigError):
    pass


class GitError(VentwigError):
    pass


class DriftError(VentwigError):
    pass


class PreconditionError(VentwigError):
    pass
