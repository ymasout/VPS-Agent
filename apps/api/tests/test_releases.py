from app.releases import release_asset_url


def test_release_asset_url_is_restricted() -> None:
    assert release_asset_url("latest", "vps-agent-linux-amd64") == (
        "https://github.com/ymasout/VPS-Agent/releases/latest/download/"
        "vps-agent-linux-amd64"
    )
    assert release_asset_url("v0.2.3", "SHA256SUMS") == (
        "https://github.com/ymasout/VPS-Agent/releases/download/v0.2.3/SHA256SUMS"
    )
    assert release_asset_url("../../main", "install-agent.sh") is None
    assert release_asset_url("latest", "unknown-file") is None
