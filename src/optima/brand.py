"""Every user-visible name lives here. scripts/rename.py rewrites it for you."""
NAME = "Optima"
FULL_NAME = "Optima AI Browser"
SLUG = "optima"
REPO_URL = "https://github.com/ascaniolocorotondo/optima-ai-browser"


def ua_suffix(version: str) -> str:
    # Honest identification: sites can see this is an AI agent.
    return f"{NAME}/{version} (AI agent; +{REPO_URL})"
