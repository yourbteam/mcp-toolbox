# Task 04: ClickUp Missing Endpoints - Implementation Plan

## Overview
Add 56 new tools to the existing `clickup_tool.py`, completing full ClickUp API v2 coverage. No new infrastructure needed — all tools use the existing `_request()`, `_get_team_id()`, `_to_ms()`, and `_success()` helpers.

**Final state:** 81 ClickUp tools, 97 tools total across the toolbox.

---

## Step 1: Groups A-C — Space, Folder, List CRUD (10 tools)

Append inside `register_tools()` after the existing Tier 4 tools.

```python
    # --- Group A: Space CRUD ---

    @mcp.tool()
    async def clickup_get_space(space_id: str) -> str:
        """Get details of a single ClickUp space.

        Args:
            space_id: Space ID
        """
        data = await _request("GET", f"/space/{space_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_space(
        space_id: str,
        name: str | None = None,
        color: str | None = None,
        private: bool | None = None,
        admin_can_manage: bool | None = None,
    ) -> str:
        """Update a ClickUp space.

        Args:
            space_id: Space ID
            name: New space name
            color: Space color hex
            private: Make space private
            admin_can_manage: Admin-only management
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if color is not None:
            body["color"] = color
        if private is not None:
            body["private"] = private
        if admin_can_manage is not None:
            body["admin_can_manage"] = admin_can_manage
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/space/{space_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_space(space_id: str) -> str:
        """Delete a ClickUp space.

        Args:
            space_id: Space ID
        """
        await _request("DELETE", f"/space/{space_id}")
        return _success(200, deleted_space_id=space_id)

    # --- Group B: Folder CRUD ---

    @mcp.tool()
    async def clickup_get_folders(space_id: str) -> str:
        """List folders in a ClickUp space.

        Args:
            space_id: Space ID
        """
        data = await _request("GET", f"/space/{space_id}/folder", params={"archived": "false"})
        folders = data.get("folders", []) if isinstance(data, dict) else data
        return _success(200, data=folders, count=len(folders))

    @mcp.tool()
    async def clickup_get_folder(folder_id: str) -> str:
        """Get details of a single ClickUp folder.

        Args:
            folder_id: Folder ID
        """
        data = await _request("GET", f"/folder/{folder_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_folder(folder_id: str, name: str) -> str:
        """Update a ClickUp folder name.

        Args:
            folder_id: Folder ID
            name: New folder name
        """
        data = await _request("PUT", f"/folder/{folder_id}", json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_folder(folder_id: str) -> str:
        """Delete a ClickUp folder.

        Args:
            folder_id: Folder ID
        """
        await _request("DELETE", f"/folder/{folder_id}")
        return _success(200, deleted_folder_id=folder_id)

    # --- Group C: List CRUD ---

    @mcp.tool()
    async def clickup_get_list(list_id: str) -> str:
        """Get details of a single ClickUp list.

        Args:
            list_id: List ID
        """
        data = await _request("GET", f"/list/{list_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_list(
        list_id: str,
        name: str | None = None,
        content: str | None = None,
        status: str | None = None,
    ) -> str:
        """Update a ClickUp list.

        Args:
            list_id: List ID
            name: New list name
            content: List description
            status: Default status
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if content is not None:
            body["content"] = content
        if status is not None:
            body["status"] = status
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/list/{list_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_list(list_id: str) -> str:
        """Delete a ClickUp list.

        Args:
            list_id: List ID
        """
        await _request("DELETE", f"/list/{list_id}")
        return _success(200, deleted_list_id=list_id)
```

---

## Step 2: Groups D-E — Comment & Checklist Management (6 tools)

```python
    # --- Group D: Comment Management ---

    @mcp.tool()
    async def clickup_update_comment(
        comment_id: str,
        comment_text: str,
        assignee: int | None = None,
    ) -> str:
        """Update a ClickUp comment.

        Args:
            comment_id: Comment ID
            comment_text: New comment text
            assignee: New assignee user ID
        """
        body: dict = {"comment_text": comment_text}
        if assignee is not None:
            body["assignee"] = assignee
        data = await _request("PUT", f"/comment/{comment_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_comment(comment_id: str) -> str:
        """Delete a ClickUp comment.

        Args:
            comment_id: Comment ID
        """
        await _request("DELETE", f"/comment/{comment_id}")
        return _success(200, deleted_comment_id=comment_id)

    # --- Group E: Checklist Management ---

    @mcp.tool()
    async def clickup_update_checklist(checklist_id: str, name: str) -> str:
        """Rename a ClickUp checklist.

        Args:
            checklist_id: Checklist ID
            name: New checklist name
        """
        data = await _request("PUT", f"/checklist/{checklist_id}", json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_checklist(checklist_id: str) -> str:
        """Delete a ClickUp checklist.

        Args:
            checklist_id: Checklist ID
        """
        await _request("DELETE", f"/checklist/{checklist_id}")
        return _success(200, deleted_checklist_id=checklist_id)

    @mcp.tool()
    async def clickup_update_checklist_item(
        checklist_id: str,
        checklist_item_id: str,
        name: str | None = None,
        resolved: bool | None = None,
        assignee: int | None = None,
    ) -> str:
        """Update or toggle a ClickUp checklist item.

        Args:
            checklist_id: Checklist ID
            checklist_item_id: Item ID
            name: New item text
            resolved: Mark as resolved/unresolved
            assignee: Assign to user ID
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if resolved is not None:
            body["resolved"] = resolved
        if assignee is not None:
            body["assignee"] = assignee
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request(
            "PUT",
            f"/checklist/{checklist_id}/checklist_item/{checklist_item_id}",
            json=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_checklist_item(
        checklist_id: str,
        checklist_item_id: str,
    ) -> str:
        """Delete a ClickUp checklist item.

        Args:
            checklist_id: Checklist ID
            checklist_item_id: Item ID
        """
        await _request(
            "DELETE",
            f"/checklist/{checklist_id}/checklist_item/{checklist_item_id}",
        )
        return _success(200, checklist_id=checklist_id, deleted_item_id=checklist_item_id)
```

---

## Step 3: Groups F-H — Time Tracking, Tags, Custom Fields (10 tools)

```python
    # --- Group F: Time Tracking Extras ---

    @mcp.tool()
    async def clickup_get_task_time(task_id: str) -> str:
        """Get time entries for a specific ClickUp task.

        Args:
            task_id: Task ID
        """
        data = await _request("GET", f"/task/{task_id}/time")
        entries = data.get("data", []) if isinstance(data, dict) else data
        return _success(200, data=entries, count=len(entries))

    @mcp.tool()
    async def clickup_delete_task_time(task_id: str, interval_id: str) -> str:
        """Delete a time entry from a ClickUp task.

        Args:
            task_id: Task ID
            interval_id: Time interval ID
        """
        await _request("DELETE", f"/task/{task_id}/time/{interval_id}")
        return _success(200, task_id=task_id, deleted_interval_id=interval_id)

    @mcp.tool()
    async def clickup_update_time_entry(
        timer_id: str,
        team_id: str | None = None,
        description: str | None = None,
        duration: int | None = None,
        start: str | int | None = None,
        end: str | int | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Update a ClickUp time entry.

        Args:
            timer_id: Time entry ID
            team_id: Workspace ID (uses default if not provided)
            description: New description
            duration: New duration in milliseconds
            start: New start time (ISO datetime or Unix ms)
            end: New end time (ISO datetime or Unix ms)
            tags: Tags for the entry
        """
        tid = _get_team_id(team_id)
        body: dict = {}
        if description is not None:
            body["description"] = description
        if duration is not None:
            body["duration"] = duration
        if start is not None:
            body["start"] = _to_ms(start)
        if end is not None:
            body["end"] = _to_ms(end)
        if tags is not None:
            body["tags"] = tags
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/team/{tid}/time_entries/{timer_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_time_entry(
        timer_id: str,
        team_id: str | None = None,
    ) -> str:
        """Delete a ClickUp time entry.

        Args:
            timer_id: Time entry ID
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        await _request("DELETE", f"/team/{tid}/time_entries/{timer_id}")
        return _success(200, deleted_timer_id=timer_id)

    @mcp.tool()
    async def clickup_get_running_timer(team_id: str | None = None) -> str:
        """Get the currently running ClickUp timer.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/time_entries/running")
        return _success(200, data=data)

    # --- Group G: Tag Management ---

    @mcp.tool()
    async def clickup_get_space_tags(space_id: str) -> str:
        """List tags in a ClickUp space.

        Args:
            space_id: Space ID
        """
        data = await _request("GET", f"/space/{space_id}/tag")
        tags = data.get("tags", []) if isinstance(data, dict) else data
        return _success(200, data=tags, count=len(tags))

    @mcp.tool()
    async def clickup_create_space_tag(
        space_id: str,
        name: str,
        tag_fg: str | None = None,
        tag_bg: str | None = None,
    ) -> str:
        """Create a tag in a ClickUp space.

        Args:
            space_id: Space ID
            name: Tag name
            tag_fg: Foreground color hex
            tag_bg: Background color hex
        """
        body: dict = {"tag": {"name": name}}
        if tag_fg is not None:
            body["tag"]["tag_fg"] = tag_fg
        if tag_bg is not None:
            body["tag"]["tag_bg"] = tag_bg
        data = await _request("POST", f"/space/{space_id}/tag", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_space_tag(
        space_id: str,
        tag_name: str,
        new_name: str | None = None,
        tag_fg: str | None = None,
        tag_bg: str | None = None,
    ) -> str:
        """Update a tag in a ClickUp space.

        Args:
            space_id: Space ID
            tag_name: Current tag name
            new_name: New tag name
            tag_fg: New foreground color
            tag_bg: New background color
        """
        body: dict = {"tag": {}}
        if new_name is not None:
            body["tag"]["name"] = new_name
        if tag_fg is not None:
            body["tag"]["tag_fg"] = tag_fg
        if tag_bg is not None:
            body["tag"]["tag_bg"] = tag_bg
        if not body["tag"]:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/space/{space_id}/tag/{tag_name}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_space_tag(space_id: str, tag_name: str) -> str:
        """Delete a tag from a ClickUp space.

        Args:
            space_id: Space ID
            tag_name: Tag name to delete
        """
        await _request("DELETE", f"/space/{space_id}/tag/{tag_name}")
        return _success(200, space_id=space_id, deleted_tag=tag_name)

    # --- Group H: Custom Field Removal ---

    @mcp.tool()
    async def clickup_remove_custom_field(task_id: str, field_id: str) -> str:
        """Remove a custom field value from a ClickUp task.

        Args:
            task_id: Task ID
            field_id: Custom field ID
        """
        await _request("DELETE", f"/task/{task_id}/field/{field_id}")
        return _success(200, task_id=task_id, removed_field_id=field_id)
```

---

## Step 4: Group I — Goals (8 tools)

```python
    # --- Group I: Goals (Business+ only) ---

    @mcp.tool()
    async def clickup_get_goals(team_id: str | None = None) -> str:
        """List ClickUp goals (Business+ plan required).

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/goal")
        goals = data.get("goals", []) if isinstance(data, dict) else data
        return _success(200, data=goals, count=len(goals))

    @mcp.tool()
    async def clickup_create_goal(
        name: str,
        team_id: str | None = None,
        due_date: str | int | None = None,
        description: str | None = None,
        color: str | None = None,
    ) -> str:
        """Create a ClickUp goal (Business+ plan required).

        Args:
            name: Goal name
            team_id: Workspace ID (uses default if not provided)
            due_date: Goal deadline (ISO datetime or Unix ms)
            description: Goal description
            color: Goal color hex
        """
        tid = _get_team_id(team_id)
        body: dict = {"name": name}
        if due_date is not None:
            body["due_date"] = _to_ms(due_date)
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        data = await _request("POST", f"/team/{tid}/goal", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_goal(goal_id: str) -> str:
        """Get ClickUp goal details.

        Args:
            goal_id: Goal ID
        """
        data = await _request("GET", f"/goal/{goal_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_goal(
        goal_id: str,
        name: str | None = None,
        due_date: str | int | None = None,
        description: str | None = None,
        color: str | None = None,
    ) -> str:
        """Update a ClickUp goal.

        Args:
            goal_id: Goal ID
            name: New goal name
            due_date: New deadline (ISO datetime or Unix ms)
            description: New description
            color: New color hex
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if due_date is not None:
            body["due_date"] = _to_ms(due_date)
        if description is not None:
            body["description"] = description
        if color is not None:
            body["color"] = color
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/goal/{goal_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_goal(goal_id: str) -> str:
        """Delete a ClickUp goal.

        Args:
            goal_id: Goal ID
        """
        await _request("DELETE", f"/goal/{goal_id}")
        return _success(200, deleted_goal_id=goal_id)

    @mcp.tool()
    async def clickup_create_key_result(
        goal_id: str,
        name: str,
        type: str,
        steps_start: int | None = None,
        steps_end: int | None = None,
        unit: str | None = None,
    ) -> str:
        """Add a key result to a ClickUp goal.

        Args:
            goal_id: Goal ID
            name: Key result name
            type: 'number', 'currency', 'boolean', 'percentage', or 'automatic'
            steps_start: Starting value
            steps_end: Target value
            unit: Unit label (e.g., '$', 'tasks')
        """
        body: dict = {"name": name, "type": type}
        if steps_start is not None:
            body["steps_start"] = steps_start
        if steps_end is not None:
            body["steps_end"] = steps_end
        if unit is not None:
            body["unit"] = unit
        data = await _request("POST", f"/goal/{goal_id}/key_result", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_key_result(
        key_result_id: str,
        steps_current: int | None = None,
        note: str | None = None,
    ) -> str:
        """Update a ClickUp key result.

        Args:
            key_result_id: Key result ID
            steps_current: Current progress value
            note: Progress note
        """
        body: dict = {}
        if steps_current is not None:
            body["steps_current"] = steps_current
        if note is not None:
            body["note"] = note
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/key_result/{key_result_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_key_result(key_result_id: str) -> str:
        """Delete a ClickUp key result.

        Args:
            key_result_id: Key result ID
        """
        await _request("DELETE", f"/key_result/{key_result_id}")
        return _success(200, deleted_key_result_id=key_result_id)
```

---

## Step 5: Groups J-K — Time Entry Details & Tags (6 tools)

```python
    # --- Group J: Time Entry Details ---

    @mcp.tool()
    async def clickup_get_time_entry(
        timer_id: str,
        team_id: str | None = None,
    ) -> str:
        """Get a single ClickUp time entry.

        Args:
            timer_id: Time entry ID
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/time_entries/{timer_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_time_entry_history(
        timer_id: str,
        team_id: str | None = None,
    ) -> str:
        """Get edit history of a ClickUp time entry.

        Args:
            timer_id: Time entry ID
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/time_entries/{timer_id}/history")
        return _success(200, data=data)

    # --- Group K: Time Entry Tags ---

    @mcp.tool()
    async def clickup_get_time_entry_tags(team_id: str | None = None) -> str:
        """List all time entry tags in a ClickUp workspace.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/time_entries/tags")
        tags = data.get("data", []) if isinstance(data, dict) else data
        return _success(200, data=tags, count=len(tags))

    @mcp.tool()
    async def clickup_add_time_entry_tags(
        time_entry_ids: list[str],
        tags: list[dict],
        team_id: str | None = None,
    ) -> str:
        """Add tags to ClickUp time entries.

        Args:
            time_entry_ids: Time entry IDs to tag
            tags: Tags to add (each: {"name": "tag_name"})
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        body = {"time_entry_ids": time_entry_ids, "tags": tags}
        data = await _request("POST", f"/team/{tid}/time_entries/tags", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_remove_time_entry_tags(
        time_entry_ids: list[str],
        tags: list[dict],
        team_id: str | None = None,
    ) -> str:
        """Remove tags from ClickUp time entries.

        Args:
            time_entry_ids: Time entry IDs to untag
            tags: Tags to remove (each: {"name": "tag_name"})
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        body = {"time_entry_ids": time_entry_ids, "tags": tags}
        data = await _request("DELETE", f"/team/{tid}/time_entries/tags", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_rename_time_entry_tag(
        name: str,
        new_name: str,
        team_id: str | None = None,
    ) -> str:
        """Rename a ClickUp time entry tag.

        Args:
            name: Current tag name
            new_name: New tag name
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        body = {"name": name, "new_name": new_name}
        data = await _request("PUT", f"/team/{tid}/time_entries/tags", json=body)
        return _success(200, data=data)
```

---

## Step 6: Group L — Views (12 tools)

```python
    # --- Group L: Views ---

    @mcp.tool()
    async def clickup_get_workspace_views(team_id: str | None = None) -> str:
        """List workspace-level views in ClickUp.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/view")
        views = data.get("views", []) if isinstance(data, dict) else data
        return _success(200, data=views, count=len(views))

    @mcp.tool()
    async def clickup_create_workspace_view(
        name: str,
        type: str,
        team_id: str | None = None,
    ) -> str:
        """Create a workspace-level view in ClickUp.

        Args:
            name: View name
            type: View type (list, board, calendar, gantt, table, timeline, workload, map, activity)
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("POST", f"/team/{tid}/view", json={"name": name, "type": type})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_space_views(space_id: str) -> str:
        """List views in a ClickUp space.

        Args:
            space_id: Space ID
        """
        data = await _request("GET", f"/space/{space_id}/view")
        views = data.get("views", []) if isinstance(data, dict) else data
        return _success(200, data=views, count=len(views))

    @mcp.tool()
    async def clickup_create_space_view(space_id: str, name: str, type: str) -> str:
        """Create a view in a ClickUp space.

        Args:
            space_id: Space ID
            name: View name
            type: View type
        """
        data = await _request(
            "POST", f"/space/{space_id}/view", json={"name": name, "type": type}
        )
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_folder_views(folder_id: str) -> str:
        """List views in a ClickUp folder.

        Args:
            folder_id: Folder ID
        """
        data = await _request("GET", f"/folder/{folder_id}/view")
        views = data.get("views", []) if isinstance(data, dict) else data
        return _success(200, data=views, count=len(views))

    @mcp.tool()
    async def clickup_create_folder_view(folder_id: str, name: str, type: str) -> str:
        """Create a view in a ClickUp folder.

        Args:
            folder_id: Folder ID
            name: View name
            type: View type
        """
        data = await _request(
            "POST", f"/folder/{folder_id}/view", json={"name": name, "type": type}
        )
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_list_views(list_id: str) -> str:
        """List views in a ClickUp list.

        Args:
            list_id: List ID
        """
        data = await _request("GET", f"/list/{list_id}/view")
        views = data.get("views", []) if isinstance(data, dict) else data
        return _success(200, data=views, count=len(views))

    @mcp.tool()
    async def clickup_create_list_view(list_id: str, name: str, type: str) -> str:
        """Create a view in a ClickUp list.

        Args:
            list_id: List ID
            name: View name
            type: View type
        """
        data = await _request(
            "POST", f"/list/{list_id}/view", json={"name": name, "type": type}
        )
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_view(view_id: str) -> str:
        """Get details of a ClickUp view.

        Args:
            view_id: View ID
        """
        data = await _request("GET", f"/view/{view_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_view(
        view_id: str,
        name: str | None = None,
        type: str | None = None,
    ) -> str:
        """Update a ClickUp view.

        Args:
            view_id: View ID
            name: New view name
            type: New view type
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if type is not None:
            body["type"] = type
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/view/{view_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_view(view_id: str) -> str:
        """Delete a ClickUp view.

        Args:
            view_id: View ID
        """
        await _request("DELETE", f"/view/{view_id}")
        return _success(200, deleted_view_id=view_id)

    @mcp.tool()
    async def clickup_get_view_tasks(view_id: str, page: int = 0) -> str:
        """Get tasks visible in a ClickUp view.

        Args:
            view_id: View ID
            page: Page number (default 0, max 100 per page)
        """
        data = await _request("GET", f"/view/{view_id}/task", params={"page": str(page)})
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        return _success(200, data=tasks, count=len(tasks), page=page)
```

---

## Step 7: Group M — Webhooks (4 tools)

```python
    # --- Group M: Webhooks ---

    @mcp.tool()
    async def clickup_get_webhooks(team_id: str | None = None) -> str:
        """List ClickUp webhooks.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/webhook")
        webhooks = data.get("webhooks", []) if isinstance(data, dict) else data
        return _success(200, data=webhooks, count=len(webhooks))

    @mcp.tool()
    async def clickup_create_webhook(
        endpoint: str,
        events: list[str],
        team_id: str | None = None,
        space_id: str | None = None,
        folder_id: str | None = None,
        list_id: str | None = None,
    ) -> str:
        """Create a ClickUp webhook.

        Args:
            endpoint: URL to receive webhook POSTs
            events: Event types (e.g., taskCreated, taskUpdated, taskDeleted,
                    taskStatusUpdated, taskAssigneeUpdated, taskCommentPosted)
            team_id: Workspace ID (uses default if not provided)
            space_id: Scope to specific space
            folder_id: Scope to specific folder
            list_id: Scope to specific list
        """
        tid = _get_team_id(team_id)
        body: dict = {"endpoint": endpoint, "events": events}
        if space_id is not None:
            body["space_id"] = space_id
        if folder_id is not None:
            body["folder_id"] = folder_id
        if list_id is not None:
            body["list_id"] = list_id
        data = await _request("POST", f"/team/{tid}/webhook", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_webhook(
        webhook_id: str,
        endpoint: str | None = None,
        events: list[str] | None = None,
        status: str | None = None,
    ) -> str:
        """Update a ClickUp webhook.

        Args:
            webhook_id: Webhook ID
            endpoint: New URL
            events: New event types
            status: 'active' or 'inactive'
        """
        body: dict = {}
        if endpoint is not None:
            body["endpoint"] = endpoint
        if events is not None:
            body["events"] = events
        if status is not None:
            body["status"] = status
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PUT", f"/webhook/{webhook_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_delete_webhook(webhook_id: str) -> str:
        """Delete a ClickUp webhook.

        Args:
            webhook_id: Webhook ID
        """
        await _request("DELETE", f"/webhook/{webhook_id}")
        return _success(200, deleted_webhook_id=webhook_id)
```

---

## Step 8: Tests

Add to the existing `tests/test_clickup_tool.py`. All tests use the existing `server` fixture and `_get_result_data()` helper. One test per tool (56 tests) plus validation error tests.

Due to the volume (56 tools), the test pattern is uniform. Each test:
1. Mocks the endpoint with `respx`
2. Calls `server.call_tool()`
3. Asserts `status == "success"`

The full test file follows the same structure as the existing 31 ClickUp tests. Representative samples for each group:

**Group A-C pattern (GET/PUT/DELETE on entity):**
```python
@pytest.mark.asyncio
@respx.mock
async def test_get_space(server):
    respx.get(f"{CLICKUP_BASE}/space/s1").mock(
        return_value=httpx.Response(200, json={"id": "s1", "name": "Eng"})
    )
    result = await server.call_tool("clickup_get_space", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"
```

**Group I pattern (Goals with team_id):**
```python
@pytest.mark.asyncio
@respx.mock
async def test_get_goals(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/goal").mock(
        return_value=httpx.Response(200, json={"goals": [{"id": "g1"}]})
    )
    result = await server.call_tool("clickup_get_goals", {})
    assert _get_result_data(result)["status"] == "success"
```

**Group L pattern (Views at multiple levels):**
```python
@pytest.mark.asyncio
@respx.mock
async def test_get_workspace_views(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/view").mock(
        return_value=httpx.Response(200, json={"views": [{"id": "v1"}]})
    )
    result = await server.call_tool("clickup_get_workspace_views", {})
    assert _get_result_data(result)["status"] == "success"
```

**Every one of the 56 new tools must have at least one test.** Validation error tests for tools with required conditional params (e.g., `clickup_update_space` with no fields).

---

## Step 9: Update test_server.py

Update the expected tool set to include all 97 tool names (41 existing + 56 new):

```python
def test_server_has_tools():
    tools = mcp._tool_manager._tools
    assert len(tools) == 97
    expected_tools = {
        # Example tools
        "hello", "add",
        # SendGrid tools (14)
        "send_email", "send_template_email", "send_email_with_attachment",
        "schedule_email", "list_templates", "get_template", "get_email_stats",
        "get_bounces", "get_spam_reports", "manage_suppressions",
        "add_contacts", "search_contacts", "get_contact", "manage_lists",
        # ClickUp existing (25)
        "clickup_get_workspaces", "clickup_get_spaces", "clickup_get_lists",
        "clickup_create_task", "clickup_get_task", "clickup_update_task",
        "clickup_get_tasks", "clickup_search_tasks", "clickup_delete_task",
        "clickup_add_comment", "clickup_get_comments", "clickup_create_checklist",
        "clickup_add_checklist_item", "clickup_add_tag", "clickup_remove_tag",
        "clickup_log_time", "clickup_get_time_entries", "clickup_start_timer",
        "clickup_stop_timer", "clickup_create_space", "clickup_create_list",
        "clickup_create_folder", "clickup_get_members", "clickup_get_custom_fields",
        "clickup_set_custom_field",
        # ClickUp new - Group A: Space CRUD (3)
        "clickup_get_space", "clickup_update_space", "clickup_delete_space",
        # ClickUp new - Group B: Folder CRUD (4)
        "clickup_get_folders", "clickup_get_folder", "clickup_update_folder",
        "clickup_delete_folder",
        # ClickUp new - Group C: List CRUD (3)
        "clickup_get_list", "clickup_update_list", "clickup_delete_list",
        # ClickUp new - Group D: Comment Management (2)
        "clickup_update_comment", "clickup_delete_comment",
        # ClickUp new - Group E: Checklist Management (4)
        "clickup_update_checklist", "clickup_delete_checklist",
        "clickup_update_checklist_item", "clickup_delete_checklist_item",
        # ClickUp new - Group F: Time Tracking Extras (5)
        "clickup_get_task_time", "clickup_delete_task_time",
        "clickup_update_time_entry", "clickup_delete_time_entry",
        "clickup_get_running_timer",
        # ClickUp new - Group G: Tag Management (4)
        "clickup_get_space_tags", "clickup_create_space_tag",
        "clickup_update_space_tag", "clickup_delete_space_tag",
        # ClickUp new - Group H: Custom Field Removal (1)
        "clickup_remove_custom_field",
        # ClickUp new - Group I: Goals (8)
        "clickup_get_goals", "clickup_create_goal", "clickup_get_goal",
        "clickup_update_goal", "clickup_delete_goal",
        "clickup_create_key_result", "clickup_update_key_result",
        "clickup_delete_key_result",
        # ClickUp new - Group J: Time Entry Details (2)
        "clickup_get_time_entry", "clickup_get_time_entry_history",
        # ClickUp new - Group K: Time Entry Tags (4)
        "clickup_get_time_entry_tags", "clickup_add_time_entry_tags",
        "clickup_remove_time_entry_tags", "clickup_rename_time_entry_tag",
        # ClickUp new - Group L: Views (12)
        "clickup_get_workspace_views", "clickup_create_workspace_view",
        "clickup_get_space_views", "clickup_create_space_view",
        "clickup_get_folder_views", "clickup_create_folder_view",
        "clickup_get_list_views", "clickup_create_list_view",
        "clickup_get_view", "clickup_update_view", "clickup_delete_view",
        "clickup_get_view_tasks",
        # ClickUp new - Group M: Webhooks (4)
        "clickup_get_webhooks", "clickup_create_webhook",
        "clickup_update_webhook", "clickup_delete_webhook",
    }
    assert set(tools.keys()) == expected_tools
```

---

## Step 10: Documentation & Validation

### 10a. Update CLAUDE.md
Update ClickUp tool count from 25 to 81 and expand tier descriptions.

### 10b. Run validation
```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Tools | Depends On |
|-------|------|-------|------------|
| 1 | Groups A-C | 10 | — |
| 2 | Groups D-E | 6 | — |
| 3 | Groups F-H | 10 | — |
| 4 | Group I | 8 | — |
| 5 | Groups J-K | 6 | — |
| 6 | Group L | 12 | — |
| 7 | Group M | 4 | — |
| 8 | Tests | 56+ | Steps 1-7 |
| 9 | test_server.py | — | Steps 1-7 |
| 10 | Docs & validation | — | Steps 1-9 |

Steps 1-7 are independent — all append to the same `register_tools()` function.

---

## Risk Notes

- **File size:** clickup_tool.py will grow to ~1500+ lines. Acceptable for a single integration but if maintenance becomes difficult, can be split into `clickup_tasks.py`, `clickup_views.py`, etc.
- **`type` parameter shadowing:** Several view tools use `type` as a parameter name, which shadows the Python builtin. The `A` ruleset (`flake8-builtins`, rule `A002`) would flag this, but `A` is not enabled in the project's ruff config (`select = ["E", "F", "I", "N", "W"]`). No linting error will occur. If `A` is ever enabled, rename to `view_type`.
- **Goals endpoints:** Require Business+ plan. Tools will work but return API errors on lower plans — this is documented in docstrings.
