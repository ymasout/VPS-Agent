import re

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REGISTRY = re.compile(r"^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?$")
_PATH_COMPONENT = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*$")


def normalize_repository(reference: str) -> str:
    """Return one conservative canonical registry/repository identity."""

    value = reference.strip()
    if not value or value != reference or any(char.isspace() for char in value) or "://" in value:
        raise ValueError("image repository is not normalized")
    name = value.split("@", 1)[0]
    slash = name.rfind("/")
    colon = name.rfind(":")
    if colon > slash:
        name = name[:colon]
    parts = name.split("/")
    if any(not part for part in parts):
        raise ValueError("image repository is invalid")
    first = parts[0].lower()
    if "." in first or ":" in first or first == "localhost":
        registry = first
        path = parts[1:]
    else:
        registry = "docker.io"
        path = parts
    if registry == "index.docker.io":
        registry = "docker.io"
    path = [part.lower() for part in path]
    if registry == "docker.io" and len(path) == 1:
        path.insert(0, "library")
    if (
        not path
        or not _REGISTRY.fullmatch(registry)
        or any(not _PATH_COMPONENT.fullmatch(part) for part in path)
    ):
        raise ValueError("image repository is invalid")
    return "/".join([registry, *path])


def parse_digest_reference(reference: str) -> tuple[str, str]:
    if reference.count("@") != 1:
        raise ValueError("image must be repository@sha256 digest")
    repository_value, digest = reference.split("@", 1)
    if not _DIGEST.fullmatch(digest):
        raise ValueError("image digest must be sha256 followed by 64 lowercase hex characters")
    repository = normalize_repository(repository_value)
    return repository, f"{repository}@{digest}"
