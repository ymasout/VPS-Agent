import json
import sys
from collections.abc import Mapping


class PrincipalDeploymentError(ValueError):
    pass


def _environment(service: object, name: str) -> Mapping[str, object]:
    if not isinstance(service, Mapping):
        raise PrincipalDeploymentError(f"{name} service configuration is missing")
    environment = service.get("environment")
    if not isinstance(environment, Mapping):
        raise PrincipalDeploymentError(f"{name} environment is missing")
    return environment


def _required_string(environment: Mapping[str, object], name: str) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value:
        raise PrincipalDeploymentError(f"{name} must be configured")
    return value


def validate_principal_deployment(document: object) -> None:
    if not isinstance(document, Mapping):
        raise PrincipalDeploymentError("compose configuration must be an object")
    services = document.get("services")
    if not isinstance(services, Mapping):
        raise PrincipalDeploymentError("compose services are missing")
    caddy = _environment(services.get("caddy"), "caddy")
    api = _environment(services.get("api"), "api")
    web = _environment(services.get("web"), "web")

    users = {
        role: _required_string(caddy, f"CADDY_{role.upper()}_USER")
        for role in ("admin", "operator", "approver")
    }
    if len(set(users.values())) != len(users):
        raise PrincipalDeploymentError("Caddy admin/operator/approver users must be distinct")
    hashes = [
        _required_string(caddy, f"CADDY_{role.upper()}_PASSWORD_HASH")
        for role in ("admin", "operator", "approver")
    ]
    if len(set(hashes)) != len(hashes):
        raise PrincipalDeploymentError("Caddy credential hashes must be distinct")
    if web.get("PRINCIPAL_WRITE_PROXY_TOKEN"):
        raise PrincipalDeploymentError("Web must not receive the principal write proxy token")

    write_context_enabled = str(api.get("PRINCIPAL_WRITE_CONTEXT_ENABLED", "false")).lower()
    if write_context_enabled != "true":
        return
    caddy_token = _required_string(caddy, "PRINCIPAL_WRITE_PROXY_TOKEN")
    api_token = _required_string(api, "PRINCIPAL_WRITE_PROXY_TOKEN")
    if caddy_token != api_token:
        raise PrincipalDeploymentError("Caddy and API write proxy tokens must match")
    try:
        bindings = json.loads(_required_string(api, "PRINCIPAL_ROLE_BINDINGS_JSON"))
    except json.JSONDecodeError as error:
        raise PrincipalDeploymentError("principal role bindings must be valid JSON") from error
    if not isinstance(bindings, list):
        raise PrincipalDeploymentError("principal role bindings must be a JSON array")
    role_subjects = {
        binding["roles"][0]: binding["auth_subject"]
        for binding in bindings
        if isinstance(binding, dict)
        and isinstance(binding.get("roles"), list)
        and len(binding["roles"]) == 1
    }
    if role_subjects.get("operator") != users["operator"]:
        raise PrincipalDeploymentError("Caddy operator user must match operator binding")
    if role_subjects.get("approver") != users["approver"]:
        raise PrincipalDeploymentError("Caddy approver user must match approver binding")


def main() -> None:
    try:
        validate_principal_deployment(json.load(sys.stdin))
    except (json.JSONDecodeError, PrincipalDeploymentError) as error:
        print(f"principal deployment preflight failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("principal deployment preflight passed")


if __name__ == "__main__":
    main()
