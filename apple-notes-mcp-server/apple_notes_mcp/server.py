#!/usr/bin/env python3
"""Apple Notes MCP Server - Provides Apple Notes access via Model Context Protocol using AppleScript."""

import json
import subprocess
from datetime import datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


def run_applescript(script: str) -> str:
    """Run an AppleScript and return the result."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr}")
    return result.stdout.strip()


def run_applescript_multi(script: str) -> str:
    """Run a multi-line AppleScript and return the result."""
    result = subprocess.run(
        ["osascript"],
        input=script,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr}")
    return result.stdout.strip()


def list_accounts() -> list[dict]:
    """List all Notes accounts."""
    script = '''
    tell application "Notes"
        set output to ""
        repeat with acc in accounts
            set accId to id of acc
            set accName to name of acc
            set output to output & accId & "||" & accName & "\\n"
        end repeat
        return output
    end tell
    '''
    result = run_applescript_multi(script)
    accounts = []
    for line in result.strip().split("\n"):
        if line and "||" in line:
            parts = line.split("||")
            accounts.append({
                "id": parts[0],
                "name": parts[1] if len(parts) > 1 else "",
            })
    return accounts


def list_folders(account_name: str = None) -> list[dict]:
    """List all folders, optionally filtered by account."""
    if account_name:
        script = f'''
        tell application "Notes"
            set output to ""
            try
                set acc to account "{account_name}"
                repeat with f in folders of acc
                    set fId to id of f
                    set fName to name of f
                    set noteCount to count of notes in f
                    set output to output & fId & "||" & fName & "||" & noteCount & "\\n"
                end repeat
            end try
            return output
        end tell
        '''
    else:
        script = '''
        tell application "Notes"
            set output to ""
            repeat with acc in accounts
                set accName to name of acc
                repeat with f in folders of acc
                    set fId to id of f
                    set fName to name of f
                    set noteCount to count of notes in f
                    set output to output & fId & "||" & fName & "||" & accName & "||" & noteCount & "\\n"
                end repeat
            end repeat
            return output
        end tell
        '''
    result = run_applescript_multi(script)
    folders = []
    for line in result.strip().split("\n"):
        if line and "||" in line:
            parts = line.split("||")
            if account_name:
                folders.append({
                    "id": parts[0],
                    "name": parts[1] if len(parts) > 1 else "",
                    "note_count": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                })
            else:
                folders.append({
                    "id": parts[0],
                    "name": parts[1] if len(parts) > 1 else "",
                    "account": parts[2] if len(parts) > 2 else "",
                    "note_count": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0,
                })
    return folders


def list_notes(folder_name: str = None, max_results: int = 50) -> list[dict]:
    """List notes, optionally filtered by folder name."""
    if folder_name:
        script = f'''
        tell application "Notes"
            set output to ""
            set noteCount to 0
            repeat with acc in accounts
                repeat with f in folders of acc
                    if name of f is "{folder_name}" then
                        repeat with n in notes of f
                            if noteCount >= {max_results} then exit repeat
                            set nId to id of n
                            set nName to name of n
                            set nDate to modification date of n
                            set nDateStr to (year of nDate as string) & "-" & (month of nDate as integer as string) & "-" & (day of nDate as string)
                            set output to output & nId & "||" & nName & "||" & nDateStr & "\\n"
                            set noteCount to noteCount + 1
                        end repeat
                    end if
                    if noteCount >= {max_results} then exit repeat
                end repeat
                if noteCount >= {max_results} then exit repeat
            end repeat
            return output
        end tell
        '''
    else:
        # Iterate through folders to get folder names properly
        script = f'''
        tell application "Notes"
            set output to ""
            set noteCount to 0
            repeat with acc in accounts
                repeat with f in folders of acc
                    set folderName to name of f
                    repeat with n in notes of f
                        if noteCount >= {max_results} then exit repeat
                        set nId to id of n
                        set nName to name of n
                        set nDate to modification date of n
                        set nDateStr to (year of nDate as string) & "-" & (month of nDate as integer as string) & "-" & (day of nDate as string)
                        set output to output & nId & "||" & nName & "||" & nDateStr & "||" & folderName & "\\n"
                        set noteCount to noteCount + 1
                    end repeat
                    if noteCount >= {max_results} then exit repeat
                end repeat
                if noteCount >= {max_results} then exit repeat
            end repeat
            return output
        end tell
        '''
    result = run_applescript_multi(script)
    notes = []
    for line in result.strip().split("\n"):
        if line and "||" in line:
            parts = line.split("||")
            note = {
                "id": parts[0],
                "name": parts[1] if len(parts) > 1 else "",
                "modification_date": parts[2] if len(parts) > 2 else "",
            }
            if not folder_name and len(parts) > 3:
                note["folder"] = parts[3]
            notes.append(note)
    return notes


def get_note(note_id: str) -> dict:
    """Get a note's content by ID."""
    # Escape the note_id for AppleScript
    escaped_id = note_id.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        set n to note id "{escaped_id}"
        set nId to id of n
        set nName to name of n
        set nBody to plaintext of n
        set nCreated to creation date of n
        set nModified to modification date of n
        set isPasswordProtected to password protected of n

        set createdStr to (year of nCreated as string) & "-" & (month of nCreated as integer as string) & "-" & (day of nCreated as string)
        set modifiedStr to (year of nModified as string) & "-" & (month of nModified as integer as string) & "-" & (day of nModified as string)

        return nId & "||DELIM||" & nName & "||DELIM||" & nBody & "||DELIM||" & createdStr & "||DELIM||" & modifiedStr & "||DELIM||" & isPasswordProtected
    end tell
    '''
    result = run_applescript_multi(script)
    parts = result.split("||DELIM||")

    return {
        "id": parts[0] if len(parts) > 0 else "",
        "name": parts[1] if len(parts) > 1 else "",
        "plaintext": parts[2] if len(parts) > 2 else "",
        "creation_date": parts[3] if len(parts) > 3 else "",
        "modification_date": parts[4] if len(parts) > 4 else "",
        "password_protected": parts[5] == "true" if len(parts) > 5 else False,
    }


def get_note_html(note_id: str) -> dict:
    """Get a note's HTML content by ID."""
    escaped_id = note_id.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        set n to note id "{escaped_id}"
        set nId to id of n
        set nName to name of n
        set nHtml to body of n
        return nId & "||DELIM||" & nName & "||DELIM||" & nHtml
    end tell
    '''
    result = run_applescript_multi(script)
    parts = result.split("||DELIM||")

    return {
        "id": parts[0] if len(parts) > 0 else "",
        "name": parts[1] if len(parts) > 1 else "",
        "html": parts[2] if len(parts) > 2 else "",
    }


def create_note(
    name: str,
    body: str,
    folder_name: str = "Notes",
    account_name: str = None,
) -> dict:
    """Create a new note."""
    # Escape for AppleScript and convert newlines to HTML <br>
    escaped_name = name.replace('"', '\\"')
    escaped_body = body.replace('"', '\\"').replace('\n', '<br>')
    escaped_folder = folder_name.replace('"', '\\"')

    # Build HTML body
    html_body = f"<html><head></head><body><h1>{escaped_name}</h1><br>{escaped_body}</body></html>"

    if account_name:
        escaped_account = account_name.replace('"', '\\"')
        script = f'''
        tell application "Notes"
            set acc to account "{escaped_account}"
            set f to folder "{escaped_folder}" of acc
            set n to make new note at f with properties {{body:"{html_body}"}}
            return id of n
        end tell
        '''
    else:
        script = f'''
        tell application "Notes"
            set f to folder "{escaped_folder}"
            set n to make new note at f with properties {{body:"{html_body}"}}
            return id of n
        end tell
        '''

    result = run_applescript_multi(script)
    return {
        "id": result,
        "name": name,
        "folder": folder_name,
    }


def update_note(note_id: str, body: str = None, name: str = None) -> dict:
    """Update an existing note's content."""
    escaped_id = note_id.replace('"', '\\"')

    if body is not None:
        # Convert newlines to <br> for HTML, and escape quotes
        escaped_body = body.replace('"', '\\"').replace('\n', '<br>')
        if name:
            escaped_name = name.replace('"', '\\"')
            html_body = f"<html><head></head><body><h1>{escaped_name}</h1><br>{escaped_body}</body></html>"
        else:
            # Get current name
            name_script = f'''
            tell application "Notes"
                return name of note id "{escaped_id}"
            end tell
            '''
            current_name = run_applescript_multi(name_script)
            escaped_name = current_name.replace('"', '\\"')
            html_body = f"<html><head></head><body><h1>{escaped_name}</h1><br>{escaped_body}</body></html>"

        script = f'''
        tell application "Notes"
            set n to note id "{escaped_id}"
            set body of n to "{html_body}"
            return id of n
        end tell
        '''
    elif name is not None:
        # Just updating the name means updating the first line/heading
        escaped_name = name.replace('"', '\\"').replace('\n', '\\n')
        script = f'''
        tell application "Notes"
            set n to note id "{escaped_id}"
            set currentBody to body of n
            -- The name is typically the h1 tag, this is a simplistic update
            set name of n to "{escaped_name}"
            return id of n
        end tell
        '''
    else:
        return {"error": "Must provide body or name to update"}

    result = run_applescript_multi(script)
    return {
        "id": result,
        "updated": True,
    }


def search_notes(query: str, max_results: int = 20) -> list[dict]:
    """Search notes by name (Apple Notes doesn't support full-text search via AppleScript)."""
    escaped_query = query.replace('"', '\\"').lower()
    script = f'''
    tell application "Notes"
        set output to ""
        set noteCount to 0
        repeat with acc in accounts
            repeat with f in folders of acc
                set folderName to name of f
                repeat with n in notes of f
                    if noteCount >= {max_results} then exit repeat
                    set nName to name of n
                    set lowerName to do shell script "echo " & quoted form of nName & " | tr '[:upper:]' '[:lower:]'"
                    if lowerName contains "{escaped_query}" then
                        set nId to id of n
                        set nDate to modification date of n
                        set nDateStr to (year of nDate as string) & "-" & (month of nDate as integer as string) & "-" & (day of nDate as string)
                        set output to output & nId & "||" & nName & "||" & nDateStr & "||" & folderName & "\\n"
                        set noteCount to noteCount + 1
                    end if
                end repeat
                if noteCount >= {max_results} then exit repeat
            end repeat
            if noteCount >= {max_results} then exit repeat
        end repeat
        return output
    end tell
    '''
    result = run_applescript_multi(script)
    notes = []
    for line in result.strip().split("\n"):
        if line and "||" in line:
            parts = line.split("||")
            notes.append({
                "id": parts[0],
                "name": parts[1] if len(parts) > 1 else "",
                "modification_date": parts[2] if len(parts) > 2 else "",
                "folder": parts[3] if len(parts) > 3 else "",
            })
    return notes


def delete_note(note_id: str) -> dict:
    """Delete a note (moves to Recently Deleted, recoverable for 30 days)."""
    escaped_id = note_id.replace('"', '\\"')

    # First get the note name for confirmation
    name_script = f'''
    tell application "Notes"
        return name of note id "{escaped_id}"
    end tell
    '''
    note_name = run_applescript_multi(name_script)

    script = f'''
    tell application "Notes"
        delete note id "{escaped_id}"
        return "deleted"
    end tell
    '''
    run_applescript_multi(script)
    return {
        "deleted": True,
        "note_id": note_id,
        "note_name": note_name,
        "recovery": "Note moved to Recently Deleted folder. Recoverable for 30 days.",
    }


def show_note(note_id: str) -> dict:
    """Show a note in the Notes app UI."""
    escaped_id = note_id.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        show note id "{escaped_id}"
        activate
        return "shown"
    end tell
    '''
    run_applescript_multi(script)
    return {"shown": True, "note_id": note_id}


# MCP Server setup
server = Server("apple-notes-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Apple Notes tools."""
    return [
        Tool(
            name="notes_list_accounts",
            description="List all Apple Notes accounts (iCloud, On My Mac, etc.).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="notes_list_folders",
            description="List all folders in Apple Notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_name": {
                        "type": "string",
                        "description": "Filter folders by account name (optional)",
                    },
                },
            },
        ),
        Tool(
            name="notes_list",
            description="List notes, optionally filtered by folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Filter notes by folder name (optional)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum notes to return (default: 50)",
                    },
                },
            },
        ),
        Tool(
            name="notes_get",
            description="Get a note's content by its ID. Returns plaintext content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note ID",
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="notes_get_html",
            description="Get a note's HTML content by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note ID",
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="notes_create",
            description="Create a new note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Note title",
                    },
                    "body": {
                        "type": "string",
                        "description": "Note content (plain text)",
                    },
                    "folder_name": {
                        "type": "string",
                        "description": "Folder to create note in (default: 'Notes')",
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Account to create note in (optional)",
                    },
                },
                "required": ["name", "body"],
            },
        ),
        Tool(
            name="notes_update",
            description="Update an existing note's content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note ID to update",
                    },
                    "body": {
                        "type": "string",
                        "description": "New note content (plain text)",
                    },
                    "name": {
                        "type": "string",
                        "description": "New note title (optional)",
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="notes_search",
            description="Search notes by name/title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (searches note titles)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="notes_delete",
            description="Delete a note (moves to Recently Deleted, recoverable for 30 days).",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note ID to delete",
                    },
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="notes_show",
            description="Show a note in the Notes app UI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "The note ID to show",
                    },
                },
                "required": ["note_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "notes_list_accounts":
            result = list_accounts()
        elif name == "notes_list_folders":
            result = list_folders(account_name=arguments.get("account_name"))
        elif name == "notes_list":
            result = list_notes(
                folder_name=arguments.get("folder_name"),
                max_results=arguments.get("max_results", 50),
            )
        elif name == "notes_get":
            result = get_note(arguments["note_id"])
        elif name == "notes_get_html":
            result = get_note_html(arguments["note_id"])
        elif name == "notes_create":
            result = create_note(
                name=arguments["name"],
                body=arguments["body"],
                folder_name=arguments.get("folder_name", "Notes"),
                account_name=arguments.get("account_name"),
            )
        elif name == "notes_update":
            result = update_note(
                note_id=arguments["note_id"],
                body=arguments.get("body"),
                name=arguments.get("name"),
            )
        elif name == "notes_search":
            result = search_notes(
                query=arguments["query"],
                max_results=arguments.get("max_results", 20),
            )
        elif name == "notes_delete":
            result = delete_note(arguments["note_id"])
        elif name == "notes_show":
            result = show_note(arguments["note_id"])
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
