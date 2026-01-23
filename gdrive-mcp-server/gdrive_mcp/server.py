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
