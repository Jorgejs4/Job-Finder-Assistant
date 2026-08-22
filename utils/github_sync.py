import json
import os
import base64
import requests
import config


def dispatch_analysis_workflow(limit: int = 0, workers: int = 1) -> tuple[bool, str]:
    """Start the durable GitHub Actions analysis job from the dashboard."""
    token = config.GITHUB_TOKEN
    if not token:
        return False, "GITHUB_TOKEN no configurado"
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/actions/workflows/analyze.yml/dispatches"
    response = requests.post(
        url,
        json={"ref": "main", "inputs": {"limit": str(max(0, limit)), "workers": str(max(1, workers))}},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=20,
    )
    if response.status_code == 204:
        return True, "Workflow de análisis iniciado en GitHub Actions"
    return False, f"GitHub respondió {response.status_code}: {response.text[:300]}"

def commit_data_json(json_path: str, commit_message: str = None) -> bool:
    token = config.GITHUB_TOKEN
    if not token:
        return False

    repo = config.GITHUB_REPO
    path_in_repo = "results/data.json"
    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"

    with open(json_path, "rb") as f:
        content = f.read()

    encoded = base64.b64encode(content).decode()

    sha = _get_current_sha(url, token)
    if sha is None:
        return False

    msg = commit_message or "sync: update data.json from dashboard"

    resp = requests.put(url, json={
        "message": msg,
        "content": encoded,
        "sha": sha,
    }, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    })

    return resp.status_code in (200, 201)

def _get_current_sha(url: str, token: str) -> str | None:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    })
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None
