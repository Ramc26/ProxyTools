# Add a server here — UI and mounting pick it up automatically.
# Required: namespace, connection ("stdio" or "http"), env_keys (list, can be [])
# stdio: package   |   http: url

EXTERNAL_SERVERS = [
    {
        "namespace": "github",
        "title": "GitHub",
        "connection": "stdio",
        "package": "@modelcontextprotocol/server-github",
        "env_keys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    },
    {
        "namespace": "postman",
        "title": "Postman",
        "connection": "http",
        "url": "https://mcp.postman.com/mcp",
        "env_keys": ["POSTMAN_API_KEY"],
    },
    {
        "namespace": "brave",
        "title": "Brave Search",
        "connection": "stdio",
        "package": "@modelcontextprotocol/server-brave-search",
        "env_keys": ["BRAVE_API_KEY"],
    },
    {
        "namespace": "gworkspace",
        "title": "Google Workspace",
        "connection": "stdio",
        "package": "@aaronsb/google-workspace-mcp",
        "env_keys": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
    },
    {
        "namespace": "gitlab",
        "title": "GitLab",
        "connection": "stdio",
        "package": "@zereight/mcp-gitlab",
        "env_keys": ["GITLAB_TOKEN_FINE"],
        "env_map": {"GITLAB_PERSONAL_ACCESS_TOKEN": "GITLAB_TOKEN_FINE"},
        "env_unset": ["GITLAB_TOKEN"],
        "env_defaults": {"GITLAB_API_URL": "https://gitlab.com/api/v4"},
    },
]