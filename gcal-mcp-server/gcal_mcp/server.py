#!/usr/bin/env python3
"""Google Calendar MCP Server - Provides Calendar API access via Model Context Protocol."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

CONFIG_DIR = Path.home() / ".config" / "gcal-mcp"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"


def get_calendar_service():
    """Get authenticated Calendar API service."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Calendar credentials not found at {CREDENTIALS_FILE}. "
                    "Please download OAuth credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def reauth() -> dict:
    """Delete existing token and re-authenticate with Google Calendar."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    # Trigger new auth flow
    get_calendar_service()

    return {"success": True, "message": "Re-authenticated successfully with Google Calendar"}


def list_calendars() -> list[dict]:
    """List all calendars."""
    service = get_calendar_service()
    results = service.calendarList().list().execute()
    calendars = results.get("items", [])
    return [
        {
            "id": cal["id"],
            "summary": cal.get("summary", ""),
            "primary": cal.get("primary", False),
            "accessRole": cal.get("accessRole", ""),
        }
        for cal in calendars
    ]


def list_events(
    calendar_id: str = "primary",
    time_min: str = None,
    time_max: str = None,
    max_results: int = 10,
    query: str = None,
) -> list[dict]:
    """List events from a calendar."""
    service = get_calendar_service()

    if not time_min:
        time_min = datetime.utcnow().isoformat() + "Z"

    params = {
        "calendarId": calendar_id,
        "timeMin": time_min,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }

    if time_max:
        params["timeMax"] = time_max
    if query:
        params["q"] = query

    results = service.events().list(**params).execute()
    events = results.get("items", [])

    return [
        {
            "id": event["id"],
            "summary": event.get("summary", "(No title)"),
            "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "")),
            "end": event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "")),
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "attendees": [a.get("email", "") for a in event.get("attendees", [])],
            "htmlLink": event.get("htmlLink", ""),
        }
        for event in events
    ]


def get_event(calendar_id: str, event_id: str) -> dict:
    """Get details of a specific event."""
    service = get_calendar_service()
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    return {
        "id": event["id"],
        "summary": event.get("summary", ""),
        "start": event.get("start", {}),
        "end": event.get("end", {}),
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "attendees": event.get("attendees", []),
        "organizer": event.get("organizer", {}),
        "status": event.get("status", ""),
        "htmlLink": event.get("htmlLink", ""),
        "conferenceData": event.get("conferenceData", {}),
        "recurrence": event.get("recurrence", []),
    }


def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: str = None,
    location: str = None,
    attendees: list[str] = None,
    timezone: str = "America/Los_Angeles",
) -> dict:
    """Create a new calendar event."""
    service = get_calendar_service()

    event = {
        "summary": summary,
        "start": {"dateTime": start_time, "timeZone": timezone},
        "end": {"dateTime": end_time, "timeZone": timezone},
    }

    if description:
        event["description"] = description
    if location:
        event["location"] = location
    if attendees:
        event["attendees"] = [{"email": email} for email in attendees]

    created = service.events().insert(calendarId=calendar_id, body=event).execute()

    return {
        "id": created["id"],
        "summary": created.get("summary", ""),
        "htmlLink": created.get("htmlLink", ""),
        "start": created.get("start", {}),
        "end": created.get("end", {}),
    }


def update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    location: str = None,
    timezone: str = "America/Los_Angeles",
    attendees: list[str] = None,
    add_attendees: list[str] = None,
) -> dict:
    """Update an existing calendar event."""
    service = get_calendar_service()

    # Get existing event
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    # Update fields if provided
    if summary is not None:
        event["summary"] = summary
    if description is not None:
        event["description"] = description
    if location is not None:
        event["location"] = location
    if start_time is not None:
        event["start"] = {"dateTime": start_time, "timeZone": timezone}
    if end_time is not None:
        event["end"] = {"dateTime": end_time, "timeZone": timezone}
    if attendees is not None:
        event["attendees"] = [{"email": email} for email in attendees]
    if add_attendees is not None:
        existing = event.get("attendees", [])
        existing_emails = {a.get("email", "").lower() for a in existing}
        for email in add_attendees:
            if email.lower() not in existing_emails:
                existing.append({"email": email})
        event["attendees"] = existing

    updated = service.events().update(
        calendarId=calendar_id, eventId=event_id, body=event
    ).execute()

    return {
        "id": updated["id"],
        "summary": updated.get("summary", ""),
        "htmlLink": updated.get("htmlLink", ""),
        "start": updated.get("start", {}),
        "end": updated.get("end", {}),
        "attendees": [a.get("email", "") for a in updated.get("attendees", [])],
    }


def delete_event(event_id: str, calendar_id: str = "primary") -> dict:
    """Delete a calendar event."""
    service = get_calendar_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return {"deleted": True, "event_id": event_id}


def quick_add_event(text: str, calendar_id: str = "primary") -> dict:
    """Create an event using natural language (e.g., 'Lunch with John tomorrow at noon')."""
    service = get_calendar_service()
    created = service.events().quickAdd(calendarId=calendar_id, text=text).execute()

    return {
        "id": created["id"],
        "summary": created.get("summary", ""),
        "htmlLink": created.get("htmlLink", ""),
        "start": created.get("start", {}),
        "end": created.get("end", {}),
    }


def get_freebusy(
    time_min: str,
    time_max: str,
    calendar_ids: list[str] = None,
) -> dict:
    """Get free/busy information for calendars."""
    service = get_calendar_service()

    if calendar_ids is None:
        calendar_ids = ["primary"]

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": cal_id} for cal_id in calendar_ids],
    }

    result = service.freebusy().query(body=body).execute()

    calendars = {}
    for cal_id, data in result.get("calendars", {}).items():
        calendars[cal_id] = {
            "busy": data.get("busy", []),
            "errors": data.get("errors", []),
        }

    return calendars


# MCP Server setup
server = Server("gcal-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Calendar tools."""
    return [
        Tool(
            name="gcal_list_calendars",
            description="List all calendars the user has access to.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="gcal_list_events",
            description="List upcoming events from a calendar.",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                    "time_min": {
                        "type": "string",
                        "description": "Start time in RFC 3339 format with timezone offset (e.g., '2024-01-15T00:00:00-08:00' or '2024-01-15T00:00:00Z'). Default: now.",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End time in RFC 3339 format with timezone offset (e.g., '2024-02-01T00:00:00-08:00' or '2024-02-01T00:00:00Z')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum events to return (default: 10)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Free text search query",
                    },
                },
            },
        ),
        Tool(
            name="gcal_get_event",
            description="Get details of a specific calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                },
                "required": ["event_id"],
            },
        ),
        Tool(
            name="gcal_create_event",
            description="Create a new calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format (e.g., '2024-01-15T10:00:00')",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in ISO format",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of attendee email addresses",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone (default: 'America/Los_Angeles')",
                    },
                },
                "required": ["summary", "start_time", "end_time"],
            },
        ),
        Tool(
            name="gcal_update_event",
            description="Update an existing calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID to update",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                    "summary": {
                        "type": "string",
                        "description": "New event title",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "New start time in ISO format",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "New end time in ISO format",
                    },
                    "description": {
                        "type": "string",
                        "description": "New event description",
                    },
                    "location": {
                        "type": "string",
                        "description": "New event location",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone (default: 'America/Los_Angeles')",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Replace all attendees with this list of email addresses",
                    },
                    "add_attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Add these email addresses to existing attendees",
                    },
                },
                "required": ["event_id"],
            },
        ),
        Tool(
            name="gcal_delete_event",
            description="Delete a calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID to delete",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                },
                "required": ["event_id"],
            },
        ),
        Tool(
            name="gcal_quick_add",
            description="Create an event using natural language (e.g., 'Lunch with John tomorrow at noon').",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Natural language description of the event",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: 'primary')",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="gcal_freebusy",
            description="Check free/busy status for calendars in a time range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Start time in RFC 3339 format with timezone offset (e.g., '2024-01-15T00:00:00-08:00' or '2024-01-15T00:00:00Z')",
                    },
                    "time_max": {
                        "type": "string",
                        "description": "End time in RFC 3339 format with timezone offset (e.g., '2024-02-01T00:00:00-08:00' or '2024-02-01T00:00:00Z')",
                    },
                    "calendar_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of calendar IDs to check (default: ['primary'])",
                    },
                },
                "required": ["time_min", "time_max"],
            },
        ),
        Tool(
            name="gcal_reauth",
            description="Re-authenticate with Google Calendar. Use this if you get token expired/revoked errors.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "gcal_list_calendars":
            result = list_calendars()
        elif name == "gcal_list_events":
            result = list_events(
                calendar_id=arguments.get("calendar_id", "primary"),
                time_min=arguments.get("time_min"),
                time_max=arguments.get("time_max"),
                max_results=arguments.get("max_results", 10),
                query=arguments.get("query"),
            )
        elif name == "gcal_get_event":
            result = get_event(
                calendar_id=arguments.get("calendar_id", "primary"),
                event_id=arguments["event_id"],
            )
        elif name == "gcal_create_event":
            result = create_event(
                summary=arguments["summary"],
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
                calendar_id=arguments.get("calendar_id", "primary"),
                description=arguments.get("description"),
                location=arguments.get("location"),
                attendees=arguments.get("attendees"),
                timezone=arguments.get("timezone", "America/Los_Angeles"),
            )
        elif name == "gcal_update_event":
            result = update_event(
                event_id=arguments["event_id"],
                calendar_id=arguments.get("calendar_id", "primary"),
                summary=arguments.get("summary"),
                start_time=arguments.get("start_time"),
                end_time=arguments.get("end_time"),
                description=arguments.get("description"),
                location=arguments.get("location"),
                timezone=arguments.get("timezone", "America/Los_Angeles"),
                attendees=arguments.get("attendees"),
                add_attendees=arguments.get("add_attendees"),
            )
        elif name == "gcal_delete_event":
            result = delete_event(
                event_id=arguments["event_id"],
                calendar_id=arguments.get("calendar_id", "primary"),
            )
        elif name == "gcal_quick_add":
            result = quick_add_event(
                text=arguments["text"],
                calendar_id=arguments.get("calendar_id", "primary"),
            )
        elif name == "gcal_freebusy":
            result = get_freebusy(
                time_min=arguments["time_min"],
                time_max=arguments["time_max"],
                calendar_ids=arguments.get("calendar_ids"),
            )
        elif name == "gcal_reauth":
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
