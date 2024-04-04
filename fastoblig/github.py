import json
import logging
import requests

def upload_issue(access_token: str, repo_url: str, title: str, body: str) -> str | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    url = f"{repo_url.replace('github.com', 'api.github.com/repos')}/issues"
    data = {
        "title": title, 
        "body": body
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code // 100 == 2:
        # success
        return response.json()['html_url']
    else:
        logging.error(response.content)

