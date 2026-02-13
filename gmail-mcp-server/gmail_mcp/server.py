#!/usr/bin/env python3
"""Gmail MCP Server - Provides Gmail API access via Model Context Protocol."""

import base64
import json
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

CONFIG_DIR = Path.home() / ".config" / "gmail-mcp"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"

# Account aliases - map friendly names to token files
ACCOUNTS = {
    "primary": "token.json",
    "secondary": "token_secondary.json",
}

# Account description for tool documentation
ACCOUNT_PARAM = {
    "type": "string",
    "description": "Gmail account to use: 'primary' (tomconerly@gmail.com) or 'secondary' (theycallhimtom@gmail.com). Default: primary",
    "enum": ["primary", "secondary"],
}


def get_token_file(account: str = "primary") -> Path:
    """Get token file path for an account."""
    if account in ACCOUNTS:
        return CONFIG_DIR / ACCOUNTS[account]
    return CONFIG_DIR / f"token_{account}.json"


def get_gmail_service(account: str = "primary"):
    """Get authenticated Gmail API service for a specific account."""
    creds = None
    token_file = get_token_file(account)

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {CREDENTIALS_FILE}."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def reauth(account: str = "primary") -> dict:
    """Delete existing token and re-authenticate with Gmail."""
    token_file = get_token_file(account)
    if token_file.exists():
        token_file.unlink()

    # Trigger new auth flow
    get_gmail_service(account)

    return {"success": True, "message": f"Re-authenticated successfully with Gmail ({account})"}


def list_accounts() -> list[dict]:
    """List configured Gmail accounts."""
    accounts = []
    for name, filename in ACCOUNTS.items():
        token_file = CONFIG_DIR / filename
        configured = token_file.exists()
        email = ""
        if configured:
            try:
                service = get_gmail_service(name)
                profile = service.users().getProfile(userId="me").execute()
                email = profile.get("emailAddress", "")
            except:
                pass
        accounts.append({"name": name, "configured": configured, "email": email})
    return accounts


def list_messages(query: str = "", max_results: int = 10, account: str = "primary") -> list[dict]:
    """List messages matching the query."""
    service = get_gmail_service(account)
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    detailed_messages = []

    for msg in messages:
        msg_detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg_detail.get("payload", {}).get("headers", [])}
        detailed_messages.append({
            "id": msg["id"],
            "threadId": msg["threadId"],
            "snippet": msg_detail.get("snippet", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
        })

    return detailed_messages


def _extract_body(payload: dict) -> str:
    """Recursively extract text/plain body from message payload."""
    # Direct body data
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

    # Check parts recursively
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
        # If no text/plain at this level, recurse into nested parts
        for part in payload["parts"]:
            if part.get("parts"):
                result = _extract_body(part)
                if result:
                    return result
    return ""


def get_message(message_id: str, account: str = "primary") -> dict:
    """Get full message content by ID."""
    service = get_gmail_service(account)
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_body(msg.get("payload", {}))

    return {
        "id": msg["id"],
        "threadId": msg["threadId"],
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body": body,
        "labels": msg.get("labelIds", []),
    }


def send_message(to: str, subject: str, body: str, account: str = "primary") -> dict:
    """Send an email message."""
    service = get_gmail_service(account)

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {"id": sent["id"], "threadId": sent["threadId"]}


def search_messages(query: str, max_results: int = 20, account: str = "primary") -> list[dict]:
    """Search messages using Gmail search syntax."""
    return list_messages(query=query, max_results=max_results, account=account)


def list_labels(account: str = "primary") -> list[dict]:
    """List all available labels."""
    service = get_gmail_service(account)
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    return [{"id": l["id"], "name": l["name"], "type": l.get("type", "")} for l in labels]


def modify_labels(message_id: str, add_labels: list[str] = None, remove_labels: list[str] = None, account: str = "primary") -> dict:
    """Add or remove labels from a message."""
    service = get_gmail_service(account)
    body = {
        "addLabelIds": add_labels or [],
        "removeLabelIds": remove_labels or [],
    }
    result = service.users().messages().modify(
        userId="me", id=message_id, body=body
    ).execute()
    return {"id": result["id"], "labels": result.get("labelIds", [])}


def archive_message(message_id: str, account: str = "primary") -> dict:
    """Archive a message by removing the INBOX label."""
    return modify_labels(message_id, remove_labels=["INBOX"], account=account)


def mark_read(message_id: str, account: str = "primary") -> dict:
    """Mark a message as read."""
    return modify_labels(message_id, remove_labels=["UNREAD"], account=account)


def mark_unread(message_id: str, account: str = "primary") -> dict:
    """Mark a message as unread."""
    return modify_labels(message_id, add_labels=["UNREAD"], account=account)


def create_draft(to: str, subject: str, body: str, account: str = "primary") -> dict:
    """Create a draft email without sending it."""
    service = get_gmail_service(account)

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()

    return {"id": draft["id"], "message_id": draft["message"]["id"]}


def create_draft_reply(message_id: str, body: str, reply_all: bool = False, account: str = "primary") -> dict:
    """Create a draft reply to an existing message."""
    service = get_gmail_service(account)

    original = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "To", "Cc", "Subject", "Message-ID", "References"]
    ).execute()

    headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
    thread_id = original["threadId"]

    message = MIMEText(body)
    reply_to = headers.get("From", "")
    message["to"] = reply_to

    if reply_all:
        cc_list = []
        if headers.get("To"):
            cc_list.append(headers["To"])
        if headers.get("Cc"):
            cc_list.append(headers["Cc"])
        if cc_list:
            message["cc"] = ", ".join(cc_list)

    subject = headers.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    message["subject"] = subject

    message_id_header = headers.get("Message-ID", "")
    if message_id_header:
        message["In-Reply-To"] = message_id_header
        references = headers.get("References", "")
        if references:
            message["References"] = f"{references} {message_id_header}"
        else:
            message["References"] = message_id_header

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw, "threadId": thread_id}}
    ).execute()

    return {"id": draft["id"], "message_id": draft["message"]["id"], "thread_id": thread_id}


def _build_forward_body(original_msg: dict, additional_text: str = "") -> str:
    """Build the body for a forwarded message."""
    headers = {h["name"]: h["value"] for h in original_msg.get("payload", {}).get("headers", [])}

    original_body = ""
    payload = original_msg.get("payload", {})
    if "body" in payload and payload["body"].get("data"):
        original_body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
    elif "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                original_body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                break

    forward_header = f"""
---------- Forwarded message ---------
From: {headers.get('From', '')}
Date: {headers.get('Date', '')}
Subject: {headers.get('Subject', '')}
To: {headers.get('To', '')}

"""

    body = ""
    if additional_text:
        body = additional_text + "\n"
    body += forward_header + original_body

    return body


def create_draft_forward(message_id: str, to: str, body: str = "", account: str = "primary") -> dict:
    """Create a draft forwarding an existing message."""
    service = get_gmail_service(account)

    original = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
    forward_body = _build_forward_body(original, body)

    message = MIMEText(forward_body)
    message["to"] = to

    subject = headers.get("Subject", "")
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}"
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()

    return {"id": draft["id"], "message_id": draft["message"]["id"]}


def forward_message(message_id: str, to: str, body: str = "", account: str = "primary") -> dict:
    """Forward an existing message immediately."""
    service = get_gmail_service(account)

    original = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
    forward_body = _build_forward_body(original, body)

    message = MIMEText(forward_body)
    message["to"] = to

    subject = headers.get("Subject", "")
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}"
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {"id": sent["id"], "threadId": sent["threadId"]}


def get_thread(thread_id: str, account: str = "primary") -> dict:
    """Get all messages in a thread (conversation)."""
    service = get_gmail_service(account)
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "To", "Subject", "Date"]
    ).execute()

    messages = []
    for msg in thread.get("messages", []):
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        messages.append({
            "id": msg["id"],
            "snippet": msg.get("snippet", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "labels": msg.get("labelIds", []),
        })

    return {
        "id": thread["id"],
        "message_count": len(messages),
        "messages": messages,
    }


def list_drafts(max_results: int = 10, account: str = "primary") -> list[dict]:
    """List draft emails."""
    service = get_gmail_service(account)
    results = service.users().drafts().list(userId="me", maxResults=max_results).execute()

    drafts = []
    for draft in results.get("drafts", []):
        draft_detail = service.users().drafts().get(
            userId="me", id=draft["id"], format="metadata"
        ).execute()
        msg = draft_detail.get("message", {})
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        drafts.append({
            "id": draft["id"],
            "message_id": msg.get("id", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "snippet": msg.get("snippet", ""),
        })

    return drafts


def get_attachment(message_id: str, attachment_id: str, account: str = "primary") -> dict:
    """Get attachment content from a message."""
    service = get_gmail_service(account)
    attachment = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()

    return {
        "size": attachment.get("size", 0),
        "data_base64": attachment.get("data", ""),
    }


def list_attachments(message_id: str, account: str = "primary") -> list[dict]:
    """List attachments in a message."""
    service = get_gmail_service(account)
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    attachments = []

    def find_attachments(parts):
        for part in parts:
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                attachments.append({
                    "id": part["body"]["attachmentId"],
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", ""),
                    "size": part["body"].get("size", 0),
                })
            if part.get("parts"):
                find_attachments(part["parts"])

    payload = msg.get("payload", {})
    if payload.get("parts"):
        find_attachments(payload["parts"])

    return attachments


# MCP Server setup
server = Server("gmail-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Gmail tools."""
    return [
        Tool(
            name="gmail_list_accounts",
            description="List configured Gmail accounts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="gmail_list",
            description="List recent emails. Optionally filter with a Gmail search query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query (e.g., 'from:someone@example.com', 'is:unread')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default: 10)",
                    },
                    "account": ACCOUNT_PARAM,
                },
            },
        ),
        Tool(
            name="gmail_get",
            description="Get the full content of a specific email by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_search",
            description="Search emails using Gmail search syntax.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query"},
                    "max_results": {"type": "integer", "description": "Max results (default: 20)"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gmail_send",
            description="Send an email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["to", "subject", "body"],
            },
        ),
        Tool(
            name="gmail_create_draft",
            description="Create a draft email without sending it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["to", "subject", "body"],
            },
        ),
        Tool(
            name="gmail_list_labels",
            description="List all available Gmail labels.",
            inputSchema={
                "type": "object",
                "properties": {"account": ACCOUNT_PARAM},
            },
        ),
        Tool(
            name="gmail_archive",
            description="Archive an email (removes from inbox, keeps in All Mail).",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_mark_read",
            description="Mark an email as read.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_mark_unread",
            description="Mark an email as unread.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_modify_labels",
            description="Add or remove labels from an email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to add"},
                    "remove_labels": {"type": "array", "items": {"type": "string"}, "description": "Label IDs to remove"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_create_draft_reply",
            description="Create a draft reply to an existing email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID to reply to"},
                    "body": {"type": "string", "description": "Reply body (plain text)"},
                    "reply_all": {"type": "boolean", "description": "Reply to all recipients (default: false)"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id", "body"],
            },
        ),
        Tool(
            name="gmail_create_draft_forward",
            description="Create a draft forwarding an existing email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID to forward"},
                    "to": {"type": "string", "description": "Recipient email address"},
                    "body": {"type": "string", "description": "Optional message above forwarded content"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id", "to"],
            },
        ),
        Tool(
            name="gmail_forward",
            description="Forward an email immediately.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID to forward"},
                    "to": {"type": "string", "description": "Recipient email address"},
                    "body": {"type": "string", "description": "Optional message above forwarded content"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id", "to"],
            },
        ),
        Tool(
            name="gmail_get_thread",
            description="Get all messages in a conversation thread.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "The Gmail thread ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["thread_id"],
            },
        ),
        Tool(
            name="gmail_list_drafts",
            description="List draft emails.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max drafts to return (default: 10)"},
                    "account": ACCOUNT_PARAM,
                },
            },
        ),
        Tool(
            name="gmail_list_attachments",
            description="List attachments in an email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_get_attachment",
            description="Download attachment content (base64-encoded).",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID"},
                    "attachment_id": {"type": "string", "description": "The attachment ID"},
                    "account": ACCOUNT_PARAM,
                },
                "required": ["message_id", "attachment_id"],
            },
        ),
        Tool(
            name="gmail_reauth",
            description="Re-authenticate with Gmail. Use this if you get token expired/revoked errors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account": ACCOUNT_PARAM,
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        account = arguments.get("account", "primary")

        if name == "gmail_list_accounts":
            result = list_accounts()
        elif name == "gmail_list":
            result = list_messages(
                query=arguments.get("query", ""),
                max_results=arguments.get("max_results", 10),
                account=account,
            )
        elif name == "gmail_get":
            result = get_message(arguments["message_id"], account=account)
        elif name == "gmail_search":
            result = search_messages(
                query=arguments["query"],
                max_results=arguments.get("max_results", 20),
                account=account,
            )
        elif name == "gmail_send":
            result = send_message(
                to=arguments["to"],
                subject=arguments["subject"],
                body=arguments["body"],
                account=account,
            )
        elif name == "gmail_create_draft":
            result = create_draft(
                to=arguments["to"],
                subject=arguments["subject"],
                body=arguments["body"],
                account=account,
            )
        elif name == "gmail_list_labels":
            result = list_labels(account=account)
        elif name == "gmail_archive":
            result = archive_message(arguments["message_id"], account=account)
        elif name == "gmail_mark_read":
            result = mark_read(arguments["message_id"], account=account)
        elif name == "gmail_mark_unread":
            result = mark_unread(arguments["message_id"], account=account)
        elif name == "gmail_modify_labels":
            result = modify_labels(
                message_id=arguments["message_id"],
                add_labels=arguments.get("add_labels"),
                remove_labels=arguments.get("remove_labels"),
                account=account,
            )
        elif name == "gmail_create_draft_reply":
            result = create_draft_reply(
                message_id=arguments["message_id"],
                body=arguments["body"],
                reply_all=arguments.get("reply_all", False),
                account=account,
            )
        elif name == "gmail_create_draft_forward":
            result = create_draft_forward(
                message_id=arguments["message_id"],
                to=arguments["to"],
                body=arguments.get("body", ""),
                account=account,
            )
        elif name == "gmail_forward":
            result = forward_message(
                message_id=arguments["message_id"],
                to=arguments["to"],
                body=arguments.get("body", ""),
                account=account,
            )
        elif name == "gmail_get_thread":
            result = get_thread(arguments["thread_id"], account=account)
        elif name == "gmail_list_drafts":
            result = list_drafts(max_results=arguments.get("max_results", 10), account=account)
        elif name == "gmail_list_attachments":
            result = list_attachments(arguments["message_id"], account=account)
        elif name == "gmail_get_attachment":
            result = get_attachment(
                message_id=arguments["message_id"],
                attachment_id=arguments["attachment_id"],
                account=account,
            )
        elif name == "gmail_reauth":
            result = reauth(account=account)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Main entry point."""
    import asyncio
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
