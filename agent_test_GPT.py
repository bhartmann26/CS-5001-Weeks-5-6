import git
import requests
import json

SYSTEM_PROMPT = """
You are a senior software engineer reviewing git changes.

Tasks:
1. Analyze the git diff.
2. Identify potential issues, bugs, or improvements.
3. Categorize the change:
   - feature
   - bugfix
   - refactor
   - docs
   - test
4. Assess risk:
   - low
   - medium
   - high

Then decide ONE action:
- CREATE_ISSUE
- CREATE_PR
- NO_ACTION

Rules:
- Your decision MUST reference evidence from the diff.
- If improvement suggestions exist but not urgent -> CREATE_ISSUE
- If code clearly fixes or adds something complete -> CREATE_PR
- If minor change -> NO_ACTION

Return JSON:

{
 "summary": "...",
 "category": "...",
 "risk": "...",
 "issues_found": ["..."],
 "decision": "...",
 "justification": "...",
 "suggested_issue_title": "...",
 "suggested_issue_body": "...",
 "suggested_pr_title": "...",
 "suggested_pr_body": "..."
}
"""


def get_git_diff(repo_path):
    repo = git.Repo(repo_path)
    diff = repo.git.diff("HEAD")

    if not diff.strip():
        return None



def ask_llama(diff):

    prompt = f"""
{SYSTEM_PROMPT}

Git Diff:
{diff}
"""

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3.2:3b",
            "prompt": prompt,
            "stream": False
        }
    )

    return response.json()["response"]

    return diff



def decide_action(ai_output):

    data = json.loads(ai_output)

    decision = data["decision"]

    if decision == "CREATE_ISSUE":
        return ("issue", data)

    elif decision == "CREATE_PR":
        return ("pr", data)

    return ("none", data)



def ask_human(action, data):

    print("\nAI Recommendation:", action)
    print("Summary:", data["summary"])
    print("Risk:", data["risk"])

    approve = input("\nApprove? (y/n): ")

    return approve.lower() == "y"



def create_issue(repo, token, title, body):

    url = f"https://api.github.com/repos/{repo}/issues"

    headers = {
        "Authorization": f"token {token}"
    }

    data = {
        "title": title,
        "body": body
    }

    r = requests.post(url, headers=headers, json=data)

    print("Issue created:", r.json()["html_url"])



def run_agent():

    repo_path = "./repo"

    diff = get_git_diff(repo_path)

    if not diff:
        print("No changes detected.")
        return

    ai_output = ask_llama(diff)

    action, data = decide_action(ai_output)

    if action == "none":
        print("No action required.")
        return

    if ask_human(action, data):

        if action == "issue":
            create_issue(
                "username/repo",
                "GITHUB_TOKEN",
                data["suggested_issue_title"],
                data["suggested_issue_body"]
            )
