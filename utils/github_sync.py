import json
import os
import base64
import requests
import config

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
