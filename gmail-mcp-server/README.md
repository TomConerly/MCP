# Gmail MCP Server

MCP server providing Gmail API access for Claude Code and other MCP clients.

## Setup

### 1. Create Google Cloud Project & Enable Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Go to **APIs & Services > Library**
4. Search for "Gmail API" and enable it

### 2. Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. If prompted, configure the OAuth consent screen:
   - User Type: **External** (or Internal if using Workspace)
   - App name: "Gmail MCP Server"
   - User support email: your email
   - Developer contact: your email
   - Scopes: Add Gmail scopes (gmail.readonly, gmail.send, gmail.modify)
   - Test users: Add your Gmail address
4. Back in Credentials, create OAuth client ID:
   - Application type: **Desktop app**
   - Name: "Gmail MCP Server"
5. Download the JSON file

### 3. Install Credentials

```bash
mkdir -p ~/.config/gmail-mcp
mv ~/Downloads/client_secret_*.json ~/.config/gmail-mcp/credentials.json
```

### 4. Install the Server

```bash
cd gmail-mcp-server
pip install -e .
```

### 5. Authenticate (First Run)

Run manually once to complete OAuth flow:

```bash
python -c "from gmail_mcp.server import get_gmail_service; get_gmail_service()"
```

This opens a browser for Google sign-in. After authorizing, a token is saved to `~/.config/gmail-mcp/token.json`.

### 6. Configure Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "python",
      "args": ["-m", "gmail_mcp.server"],
      "cwd": "/Users/tomconerly/Documents/TCEverything/gmail-mcp-server"
    }
  }
}
```

Or using the installed script:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "gmail-mcp"
    }
  }
}
```

## Available Tools

- **gmail_list** - List recent emails with optional query filter
- **gmail_get** - Get full email content by ID
- **gmail_search** - Search emails using Gmail syntax
- **gmail_send** - Send an email

## Gmail Search Syntax

- `from:someone@example.com` - From specific sender
- `to:someone@example.com` - To specific recipient
- `subject:meeting` - Subject contains "meeting"
- `is:unread` - Unread messages
- `is:starred` - Starred messages
- `has:attachment` - Has attachments
- `after:2024/01/01` - After date
- `before:2024/12/31` - Before date
- `label:important` - Has label
