#!/usr/bin/env python3
"""Google Drive MCP Server - Provides Drive API access via Model Context Protocol."""

import io
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

CONFIG_DIR = Path.home() / ".config" / "gdrive-mcp"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"


def get_drive_service():
    """Get authenticated Drive API service."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Drive credentials not found at {CREDENTIALS_FILE}. "
                    "Please download OAuth credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def reauth() -> dict:
    """Delete existing token and re-authenticate with Google Drive."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    # Trigger new auth flow
    get_drive_service()

    return {"success": True, "message": "Re-authenticated successfully with Google Drive"}


def get_sheets_service():
    """Get authenticated Sheets API service."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Credentials not found at {CREDENTIALS_FILE}. "
                    "Please download OAuth credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def list_files(
    query: str = None,
    page_size: int = 20,
    folder_id: str = None,
    order_by: str = "modifiedTime desc",
) -> list[dict]:
    """List files in Drive."""
    service = get_drive_service()

    q_parts = []
    if query:
        q_parts.append(query)
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")

    params = {
        "pageSize": page_size,
        "fields": "files(id, name, mimeType, size, modifiedTime, parents, webViewLink)",
        "orderBy": order_by,
    }

    if q_parts:
        params["q"] = " and ".join(q_parts)

    results = service.files().list(**params).execute()
    files = results.get("files", [])

    return [
        {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "size": f.get("size", ""),
            "modifiedTime": f.get("modifiedTime", ""),
            "parents": f.get("parents", []),
            "webViewLink": f.get("webViewLink", ""),
        }
        for f in files
    ]


def search_files(query: str, page_size: int = 20) -> list[dict]:
    """Search files by name or content."""
    # Build search query for name contains
    search_query = f"name contains '{query}' or fullText contains '{query}'"
    return list_files(query=search_query, page_size=page_size)


def get_file_metadata(file_id: str) -> dict:
    """Get detailed metadata for a file."""
    service = get_drive_service()
    file = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, size, modifiedTime, createdTime, parents, webViewLink, owners, shared, permissions",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "mimeType": file["mimeType"],
        "size": file.get("size", ""),
        "modifiedTime": file.get("modifiedTime", ""),
        "createdTime": file.get("createdTime", ""),
        "parents": file.get("parents", []),
        "webViewLink": file.get("webViewLink", ""),
        "owners": file.get("owners", []),
        "shared": file.get("shared", False),
    }


def read_file_content(file_id: str) -> dict:
    """Read content of a file (text files, Google Docs, Sheets, etc.)."""
    service = get_drive_service()

    # Get file metadata to determine type
    file = service.files().get(fileId=file_id, fields="mimeType, name").execute()
    mime_type = file["mimeType"]

    # Export Google Docs/Sheets/Slides as text
    export_mime_types = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.presentation": "text/plain",
    }

    if mime_type in export_mime_types:
        content = service.files().export(
            fileId=file_id, mimeType=export_mime_types[mime_type]
        ).execute()
        return {
            "id": file_id,
            "name": file["name"],
            "mimeType": mime_type,
            "content": content.decode("utf-8") if isinstance(content, bytes) else content,
        }
    else:
        # Download binary file
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        content = fh.getvalue()
        try:
            text_content = content.decode("utf-8")
            return {
                "id": file_id,
                "name": file["name"],
                "mimeType": mime_type,
                "content": text_content,
            }
        except UnicodeDecodeError:
            return {
                "id": file_id,
                "name": file["name"],
                "mimeType": mime_type,
                "content": f"[Binary file, {len(content)} bytes]",
                "size": len(content),
            }


def create_file(
    name: str,
    content: str,
    mime_type: str = "text/plain",
    folder_id: str = None,
) -> dict:
    """Create a new file in Drive."""
    service = get_drive_service()

    file_metadata = {"name": name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=True,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "webViewLink": file.get("webViewLink", ""),
    }


def update_file_content(file_id: str, content: str, mime_type: str = "text/plain") -> dict:
    """Update content of an existing file."""
    service = get_drive_service()

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=True,
    )

    file = service.files().update(
        fileId=file_id,
        media_body=media,
        fields="id, name, modifiedTime, webViewLink",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "modifiedTime": file.get("modifiedTime", ""),
        "webViewLink": file.get("webViewLink", ""),
    }


def delete_file(file_id: str) -> dict:
    """Delete a file (moves to trash)."""
    service = get_drive_service()
    service.files().delete(fileId=file_id).execute()
    return {"deleted": True, "file_id": file_id}


def create_folder(name: str, parent_id: str = None) -> dict:
    """Create a new folder in Drive."""
    service = get_drive_service()

    file_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        file_metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=file_metadata,
        fields="id, name, webViewLink",
    ).execute()

    return {
        "id": folder["id"],
        "name": folder["name"],
        "webViewLink": folder.get("webViewLink", ""),
    }


def move_file(file_id: str, new_folder_id: str) -> dict:
    """Move a file to a different folder."""
    service = get_drive_service()

    # Get current parents
    file = service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))

    # Move file
    file = service.files().update(
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=previous_parents,
        fields="id, name, parents, webViewLink",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "parents": file.get("parents", []),
        "webViewLink": file.get("webViewLink", ""),
    }


def share_file(file_id: str, email: str, role: str = "reader") -> dict:
    """Share a file with someone."""
    service = get_drive_service()

    permission = {
        "type": "user",
        "role": role,  # reader, writer, commenter
        "emailAddress": email,
    }

    result = service.permissions().create(
        fileId=file_id,
        body=permission,
        sendNotificationEmail=True,
        fields="id, role, emailAddress",
    ).execute()

    return {
        "permission_id": result["id"],
        "role": result["role"],
        "email": result.get("emailAddress", email),
        "file_id": file_id,
    }


def copy_file(file_id: str, new_name: str = None, folder_id: str = None) -> dict:
    """Copy a file."""
    service = get_drive_service()

    body = {}
    if new_name:
        body["name"] = new_name
    if folder_id:
        body["parents"] = [folder_id]

    file = service.files().copy(
        fileId=file_id,
        body=body,
        fields="id, name, webViewLink",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "webViewLink": file.get("webViewLink", ""),
    }


def create_google_doc(
    name: str,
    content: str,
    content_type: str = "html",
    folder_id: str = None,
) -> dict:
    """Create a native Google Doc by converting from HTML or plain text.

    Args:
        name: Document name
        content: HTML or plain text content to convert
        content_type: "html" or "text" - format of the input content
        folder_id: Optional parent folder ID
    """
    service = get_drive_service()

    file_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.document",  # Target: native Google Doc
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    # Upload mime type based on content type
    upload_mime = "text/html" if content_type == "html" else "text/plain"

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=upload_mime,
        resumable=True,
    )

    # Create with conversion enabled
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()

    return {
        "id": file["id"],
        "name": file["name"],
        "webViewLink": file.get("webViewLink", ""),
    }


def list_comments(file_id: str, include_resolved: bool = False) -> list[dict]:
    """List comments on a file."""
    service = get_drive_service()

    comments = []
    page_token = None
    while True:
        params = {
            "fileId": file_id,
            "fields": "comments(id, content, resolved, author, createdTime, modifiedTime, quotedFileContent, anchor, replies(id, content, author, createdTime, action)),nextPageToken",
            "pageSize": 100,
            "includeDeleted": False,
        }
        if page_token:
            params["pageToken"] = page_token

        result = service.comments().list(**params).execute()

        for c in result.get("comments", []):
            if not include_resolved and c.get("resolved"):
                continue
            comment = {
                "id": c["id"],
                "content": c.get("content", ""),
                "resolved": c.get("resolved", False),
                "author": c.get("author", {}).get("displayName", ""),
                "createdTime": c.get("createdTime", ""),
                "modifiedTime": c.get("modifiedTime", ""),
            }
            if c.get("quotedFileContent"):
                comment["quotedText"] = c["quotedFileContent"].get("value", "")
            if c.get("replies"):
                comment["replies"] = [
                    {
                        "id": r["id"],
                        "content": r.get("content", ""),
                        "author": r.get("author", {}).get("displayName", ""),
                        "createdTime": r.get("createdTime", ""),
                        "action": r.get("action", ""),
                    }
                    for r in c["replies"]
                ]
            comments.append(comment)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return comments


def create_comment(file_id: str, content: str, quoted_text: str = None) -> dict:
    """Create a comment on a file."""
    service = get_drive_service()

    body = {"content": content}
    if quoted_text:
        body["quotedFileContent"] = {"value": quoted_text, "mimeType": "text/plain"}

    result = service.comments().create(
        fileId=file_id,
        body=body,
        fields="id, content, author, createdTime",
    ).execute()

    return {
        "id": result["id"],
        "content": result.get("content", ""),
        "author": result.get("author", {}).get("displayName", ""),
        "createdTime": result.get("createdTime", ""),
    }


def reply_to_comment(file_id: str, comment_id: str, content: str) -> dict:
    """Reply to a comment on a file."""
    service = get_drive_service()

    result = service.replies().create(
        fileId=file_id,
        commentId=comment_id,
        body={"content": content},
        fields="id, content, author, createdTime",
    ).execute()

    return {
        "id": result["id"],
        "content": result.get("content", ""),
        "author": result.get("author", {}).get("displayName", ""),
        "createdTime": result.get("createdTime", ""),
    }


def resolve_comment(file_id: str, comment_id: str, resolved: bool = True) -> dict:
    """Resolve or unresolve a comment on a file."""
    service = get_drive_service()

    # To resolve, we create a reply with action "resolve"; to unresolve, action "reopen"
    action = "resolve" if resolved else "reopen"

    result = service.replies().create(
        fileId=file_id,
        commentId=comment_id,
        body={"content": "", "action": action},
        fields="id, content, author, createdTime, action",
    ).execute()

    return {
        "id": result["id"],
        "action": result.get("action", ""),
        "createdTime": result.get("createdTime", ""),
    }


def list_spreadsheet_sheets(file_id: str) -> dict:
    """List all sheets in a Google Spreadsheet."""
    service = get_sheets_service()

    spreadsheet = service.spreadsheets().get(
        spreadsheetId=file_id,
        fields="properties.title,sheets.properties"
    ).execute()

    sheets = []
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        sheets.append({
            "sheetId": props.get("sheetId"),
            "title": props.get("title"),
            "index": props.get("index"),
            "rowCount": props.get("gridProperties", {}).get("rowCount"),
            "columnCount": props.get("gridProperties", {}).get("columnCount"),
        })

    return {
        "spreadsheetId": file_id,
        "title": spreadsheet.get("properties", {}).get("title"),
        "sheets": sheets,
    }


def read_spreadsheet_sheet(file_id: str, sheet_name: str = None) -> dict:
    """Read a specific sheet from a Google Spreadsheet.

    Args:
        file_id: The spreadsheet ID
        sheet_name: Name of the sheet to read. If None, reads the first sheet.
    """
    service = get_sheets_service()

    # If no sheet name, get the first sheet's name
    if not sheet_name:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=file_id,
            fields="sheets.properties.title"
        ).execute()
        sheets = spreadsheet.get("sheets", [])
        if sheets:
            sheet_name = sheets[0].get("properties", {}).get("title", "Sheet1")
        else:
            sheet_name = "Sheet1"

    # Read all data from the sheet
    result = service.spreadsheets().values().get(
        spreadsheetId=file_id,
        range=sheet_name,
    ).execute()

    values = result.get("values", [])

    return {
        "spreadsheetId": file_id,
        "sheetName": sheet_name,
        "range": result.get("range"),
        "rowCount": len(values),
        "values": values,
    }


def read_all_spreadsheet_sheets(file_id: str) -> dict:
    """Read all sheets from a Google Spreadsheet."""
    service = get_sheets_service()

    # Get spreadsheet metadata
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=file_id,
        fields="properties.title,sheets.properties.title"
    ).execute()

    spreadsheet_title = spreadsheet.get("properties", {}).get("title")
    sheet_names = [
        sheet.get("properties", {}).get("title")
        for sheet in spreadsheet.get("sheets", [])
    ]

    # Build ranges for all sheets
    ranges = [name for name in sheet_names if name]

    # Batch get all sheets
    result = service.spreadsheets().values().batchGet(
        spreadsheetId=file_id,
        ranges=ranges,
    ).execute()

    sheets_data = []
    for value_range in result.get("valueRanges", []):
        sheet_range = value_range.get("range", "")
        # Extract sheet name from range (e.g., "'Sheet Name'!A1:Z100" -> "Sheet Name")
        sheet_name = sheet_range.split("!")[0].strip("'")
        values = value_range.get("values", [])
        sheets_data.append({
            "sheetName": sheet_name,
            "range": sheet_range,
            "rowCount": len(values),
            "values": values,
        })

    return {
        "spreadsheetId": file_id,
        "title": spreadsheet_title,
        "sheetCount": len(sheets_data),
        "sheets": sheets_data,
    }


# MCP Server setup
server = Server("gdrive-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Drive tools."""
    return [
        Tool(
            name="gdrive_list_files",
            description="List files in Google Drive. Can filter by folder or custom query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Drive API query (e.g., \"mimeType='application/pdf'\")",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "List files in a specific folder",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Max files to return (default: 20)",
                    },
                    "order_by": {
                        "type": "string",
                        "description": "Sort order (default: 'modifiedTime desc')",
                    },
                },
            },
        ),
        Tool(
            name="gdrive_search",
            description="Search files by name or content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Max results (default: 20)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gdrive_get_file",
            description="Get metadata for a specific file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_read_file",
            description="Read content of a file. Works with text files, Google Docs, Sheets (as CSV), etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to read",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_create_file",
            description="Create a new file in Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "File name",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content",
                    },
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: 'text/plain')",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Parent folder ID (optional)",
                    },
                },
                "required": ["name", "content"],
            },
        ),
        Tool(
            name="gdrive_update_file",
            description="Update content of an existing file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to update",
                    },
                    "content": {
                        "type": "string",
                        "description": "New file content",
                    },
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: 'text/plain')",
                    },
                },
                "required": ["file_id", "content"],
            },
        ),
        Tool(
            name="gdrive_delete_file",
            description="Delete a file (moves to trash).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to delete",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_create_folder",
            description="Create a new folder in Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Folder name",
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Parent folder ID (optional)",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="gdrive_move_file",
            description="Move a file to a different folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to move",
                    },
                    "new_folder_id": {
                        "type": "string",
                        "description": "Destination folder ID",
                    },
                },
                "required": ["file_id", "new_folder_id"],
            },
        ),
        Tool(
            name="gdrive_share_file",
            description="Share a file with someone.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to share",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address to share with",
                    },
                    "role": {
                        "type": "string",
                        "description": "Permission role: 'reader', 'writer', or 'commenter' (default: 'reader')",
                    },
                },
                "required": ["file_id", "email"],
            },
        ),
        Tool(
            name="gdrive_copy_file",
            description="Make a copy of a file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to copy",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "Name for the copy (optional)",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Destination folder ID (optional)",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_create_google_doc",
            description="Create a native Google Doc by converting from HTML or plain text content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Document name",
                    },
                    "content": {
                        "type": "string",
                        "description": "HTML or plain text content to convert to Google Doc",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Format of input content: 'html' or 'text' (default: 'html')",
                        "enum": ["html", "text"],
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Parent folder ID (optional)",
                    },
                },
                "required": ["name", "content"],
            },
        ),
        Tool(
            name="gdrive_list_comments",
            description="List comments on a Google Drive file (e.g., Google Doc). Returns comment text, author, quoted text, replies, and resolved status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID",
                    },
                    "include_resolved": {
                        "type": "boolean",
                        "description": "Include resolved comments (default: false)",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_create_comment",
            description="Add a comment to a Google Drive file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID",
                    },
                    "content": {
                        "type": "string",
                        "description": "The comment text",
                    },
                    "quoted_text": {
                        "type": "string",
                        "description": "Text from the document to anchor the comment to (optional)",
                    },
                },
                "required": ["file_id", "content"],
            },
        ),
        Tool(
            name="gdrive_reply_to_comment",
            description="Reply to an existing comment on a Google Drive file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID",
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "The comment ID to reply to",
                    },
                    "content": {
                        "type": "string",
                        "description": "The reply text",
                    },
                },
                "required": ["file_id", "comment_id", "content"],
            },
        ),
        Tool(
            name="gdrive_resolve_comment",
            description="Resolve or reopen a comment on a Google Drive file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID",
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "The comment ID to resolve/reopen",
                    },
                    "resolved": {
                        "type": "boolean",
                        "description": "True to resolve, false to reopen (default: true)",
                    },
                },
                "required": ["file_id", "comment_id"],
            },
        ),
        Tool(
            name="gdrive_list_sheets",
            description="List all sheets (tabs) in a Google Spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The spreadsheet file ID",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_read_sheet",
            description="Read a specific sheet from a Google Spreadsheet. Returns all cell values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The spreadsheet file ID",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Name of the sheet to read (optional, defaults to first sheet)",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_read_all_sheets",
            description="Read all sheets from a Google Spreadsheet. Returns all cell values from every sheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The spreadsheet file ID",
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="gdrive_reauth",
            description="Re-authenticate with Google Drive. Use this if you get token expired/revoked errors.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "gdrive_list_files":
            result = list_files(
                query=arguments.get("query"),
                folder_id=arguments.get("folder_id"),
                page_size=arguments.get("page_size", 20),
                order_by=arguments.get("order_by", "modifiedTime desc"),
            )
        elif name == "gdrive_search":
            result = search_files(
                query=arguments["query"],
                page_size=arguments.get("page_size", 20),
            )
        elif name == "gdrive_get_file":
            result = get_file_metadata(arguments["file_id"])
        elif name == "gdrive_read_file":
            result = read_file_content(arguments["file_id"])
        elif name == "gdrive_create_file":
            result = create_file(
                name=arguments["name"],
                content=arguments["content"],
                mime_type=arguments.get("mime_type", "text/plain"),
                folder_id=arguments.get("folder_id"),
            )
        elif name == "gdrive_update_file":
            result = update_file_content(
                file_id=arguments["file_id"],
                content=arguments["content"],
                mime_type=arguments.get("mime_type", "text/plain"),
            )
        elif name == "gdrive_delete_file":
            result = delete_file(arguments["file_id"])
        elif name == "gdrive_create_folder":
            result = create_folder(
                name=arguments["name"],
                parent_id=arguments.get("parent_id"),
            )
        elif name == "gdrive_move_file":
            result = move_file(
                file_id=arguments["file_id"],
                new_folder_id=arguments["new_folder_id"],
            )
        elif name == "gdrive_share_file":
            result = share_file(
                file_id=arguments["file_id"],
                email=arguments["email"],
                role=arguments.get("role", "reader"),
            )
        elif name == "gdrive_copy_file":
            result = copy_file(
                file_id=arguments["file_id"],
                new_name=arguments.get("new_name"),
                folder_id=arguments.get("folder_id"),
            )
        elif name == "gdrive_create_google_doc":
            result = create_google_doc(
                name=arguments["name"],
                content=arguments["content"],
                content_type=arguments.get("content_type", "html"),
                folder_id=arguments.get("folder_id"),
            )
        elif name == "gdrive_list_comments":
            result = list_comments(
                file_id=arguments["file_id"],
                include_resolved=arguments.get("include_resolved", False),
            )
        elif name == "gdrive_create_comment":
            result = create_comment(
                file_id=arguments["file_id"],
                content=arguments["content"],
                quoted_text=arguments.get("quoted_text"),
            )
        elif name == "gdrive_reply_to_comment":
            result = reply_to_comment(
                file_id=arguments["file_id"],
                comment_id=arguments["comment_id"],
                content=arguments["content"],
            )
        elif name == "gdrive_resolve_comment":
            result = resolve_comment(
                file_id=arguments["file_id"],
                comment_id=arguments["comment_id"],
                resolved=arguments.get("resolved", True),
            )
        elif name == "gdrive_list_sheets":
            result = list_spreadsheet_sheets(arguments["file_id"])
        elif name == "gdrive_read_sheet":
            result = read_spreadsheet_sheet(
                file_id=arguments["file_id"],
                sheet_name=arguments.get("sheet_name"),
            )
        elif name == "gdrive_read_all_sheets":
            result = read_all_spreadsheet_sheets(arguments["file_id"])
        elif name == "gdrive_reauth":
            result = reauth()
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
