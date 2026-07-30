import copy
import json

import pytest

from app.principal_deployment import (
    PrincipalDeploymentError,
    validate_principal_deployment,
)


def deployment_config() -> dict:
    bindings = [
        {"auth_subject": "ops-alice", "roles": ["operator"]},
        {"auth_subject": "ops-bob", "roles": ["approver"]},
    ]
    return {
        "services": {
            "caddy": {
                "environment": {
                    "CADDY_ADMIN_USER": "admin",
                    "CADDY_ADMIN_PASSWORD_HASH": "admin-hash",
                    "CADDY_OPERATOR_USER": "ops-alice",
                    "CADDY_OPERATOR_PASSWORD_HASH": "operator-hash",
                    "CADDY_APPROVER_USER": "ops-bob",
                    "CADDY_APPROVER_PASSWORD_HASH": "approver-hash",
                    "PRINCIPAL_WRITE_PROXY_TOKEN": "write-token",
                }
            },
            "api": {
                "environment": {
                    "PRINCIPAL_WRITE_CONTEXT_ENABLED": "true",
                    "PRINCIPAL_WRITE_PROXY_TOKEN": "write-token",
                    "PRINCIPAL_ROLE_BINDINGS_JSON": json.dumps(bindings),
                }
            },
            "web": {"environment": {}},
        }
    }


def test_principal_deployment_requires_distinct_matching_credentials() -> None:
    validate_principal_deployment(deployment_config())

    duplicate_user = copy.deepcopy(deployment_config())
    duplicate_user["services"]["caddy"]["environment"]["CADDY_APPROVER_USER"] = (
        "ops-alice"
    )
    with pytest.raises(PrincipalDeploymentError, match="users must be distinct"):
        validate_principal_deployment(duplicate_user)

    wrong_binding = copy.deepcopy(deployment_config())
    wrong_binding["services"]["api"]["environment"][
        "PRINCIPAL_ROLE_BINDINGS_JSON"
    ] = json.dumps([{"auth_subject": "other", "roles": ["operator"]}])
    with pytest.raises(PrincipalDeploymentError, match="operator user must match"):
        validate_principal_deployment(wrong_binding)


def test_principal_deployment_keeps_write_token_out_of_web() -> None:
    document = deployment_config()
    document["services"]["web"]["environment"][
        "PRINCIPAL_WRITE_PROXY_TOKEN"
    ] = "write-token"
    with pytest.raises(PrincipalDeploymentError, match="Web must not receive"):
        validate_principal_deployment(document)


def test_principal_deployment_requires_api_web_enforcement_parity() -> None:
    document = deployment_config()
    document["services"]["api"]["environment"][
        "PRINCIPAL_WRITE_AUTHORIZATION_ENABLED"
    ] = "true"
    with pytest.raises(PrincipalDeploymentError, match="flags must match"):
        validate_principal_deployment(document)

    document["services"]["web"]["environment"][
        "PRINCIPAL_WRITE_AUTHORIZATION_ENABLED"
    ] = "true"
    validate_principal_deployment(document)


def test_disabled_context_still_requires_three_distinct_caddy_credentials() -> None:
    document = deployment_config()
    document["services"]["api"]["environment"][
        "PRINCIPAL_WRITE_CONTEXT_ENABLED"
    ] = "false"
    document["services"]["api"]["environment"]["PRINCIPAL_ROLE_BINDINGS_JSON"] = "[]"
    validate_principal_deployment(document)
