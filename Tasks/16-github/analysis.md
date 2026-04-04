# Task 16: GitHub Integration - Analysis & Requirements

## Objective
Add GitHub as a tool integration in mcp-toolbox, exposing repository management, issues, pull requests, branches, releases, actions, search, and social features as MCP tools for LLM clients.

---

## API Technical Details

### GitHub REST API v3
- **Base URL:** `https://api.github.com`
- **Auth:** Personal Access Token — `Authorization: Bearer ghp_xxx` (also accepts `token ghp_xxx` format)
- **Format:** JSON request/response; `Accept: application/vnd.github+json` recommended
- **API Version Header:** `X-GitHub-Api-Version: 2022-11-28` (recommended for stability)

### Rate Limits

| Limit Type | Description |
|------------|-------------|
| **Authenticated requests** | 5,000 requests per hour per user/token |
| **Search API** | 30 requests per minute for authenticated users (except Search Code: 9 requests per minute) |
| **Secondary rate limits** | Concurrent request throttling; creating content too quickly triggers abuse detection |

- HTTP 403 with `X-RateLimit-Remaining: 0` when primary limit exceeded
- HTTP 403 with `Retry-After` header for secondary/abuse limits
- HTTP 429 for secondary rate limits (newer behavior)
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix epoch seconds)

### Key Quirks
- **Owner/repo path convention** — Most endpoints use `repos/{owner}/{repo}/...` pattern. Default owner/repo can reduce repetition.
- **Pagination** — Link-header pagination with `page` + `per_page` query params (default 30, max 100). Response includes `Link` header with `rel="next"`, `rel="last"`.
- **Merge strategies** — PR merge supports `merge`, `squash`, and `rebase` methods.
- **Review states** — Reviews can be `APPROVE`, `REQUEST_CHANGES`, or `COMMENT`.
- **Search qualifiers** — Search uses a qualifier syntax in the `q` parameter (e.g., `repo:owner/name is:open type:issue label:bug`).
- **Draft PRs** — Creating a draft PR requires `draft: true` in the body.
- **Branch creation** — No dedicated endpoint; branches are created via the Git References API (`POST /repos/{owner}/{repo}/git/refs`), requiring a SHA to point to.
- **Workflow dispatch** — Triggering a workflow requires the workflow file name or ID and a `ref` (branch/tag).
- **Boolean query params** — Some endpoints accept `true`/`false` strings, not JSON booleans.
- **Empty response codes** — DELETE operations return 204 No Content; some POST operations return 201 or 202.

---

## Tool Specifications

### Tier 1: Repositories (7 tools)

#### `github_list_repos`
List repositories for the authenticated user or a specified user/org.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | User or org name (default: authenticated user's repos) |
| `type` | str | No | Repo type: `all`, `owner`, `public`, `private`, `member` (for user); `all`, `public`, `private`, `forks`, `sources`, `member` (for org) |
| `sort` | str | No | Sort by: `created`, `updated`, `pushed`, `full_name` (default `full_name`) |
| `direction` | str | No | Sort direction: `asc` or `desc` |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of repositories with id, name, full_name, description, private, html_url, default_branch, language, stargazers_count, forks_count.
**Endpoint:** `GET /user/repos` (authenticated user) or `GET /users/{owner}/repos` or `GET /orgs/{owner}/repos`

#### `github_get_repo`
Get details for a specific repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses GITHUB_DEFAULT_OWNER if not provided) |
| `repo` | str | No | Repository name (uses GITHUB_DEFAULT_REPO if not provided) |

**Returns:** Full repository object with id, name, description, private, html_url, default_branch, language, topics, license, open_issues_count, stargazers_count, forks_count, created_at, updated_at.
**Endpoint:** `GET /repos/{owner}/{repo}`

#### `github_create_repo`
Create a new repository for the authenticated user or an organization.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Repository name |
| `description` | str | No | Short description |
| `private` | bool | No | Whether repo is private (default false) |
| `auto_init` | bool | No | Initialize with README (default false) |
| `gitignore_template` | str | No | Gitignore template name (e.g., `Python`, `Node`) |
| `license_template` | str | No | License keyword (e.g., `mit`, `apache-2.0`) |
| `org` | str | No | Organization name (creates org repo if provided) |
| `has_issues` | bool | No | Enable issues (default true) |
| `has_projects` | bool | No | Enable projects (default true) |
| `has_wiki` | bool | No | Enable wiki (default true) |

**Returns:** Created repository object with id, name, full_name, html_url, clone_url, default_branch.
**Endpoint:** `POST /user/repos` (user) or `POST /orgs/{org}/repos` (org)

#### `github_update_repo`
Update repository settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `name` | str | No | New repository name |
| `description` | str | No | New description |
| `private` | bool | No | Change visibility |
| `default_branch` | str | No | Change default branch |
| `has_issues` | bool | No | Enable/disable issues |
| `has_projects` | bool | No | Enable/disable projects |
| `has_wiki` | bool | No | Enable/disable wiki |
| `archived` | bool | No | Archive or unarchive repo |

**Returns:** Updated repository object.
**Endpoint:** `PATCH /repos/{owner}/{repo}`

#### `github_delete_repo`
Delete a repository. Requires admin access.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}`

#### `github_list_repo_topics`
List topics (tags) for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |

**Returns:** List of topic name strings.
**Endpoint:** `GET /repos/{owner}/{repo}/topics`

#### `github_list_repo_languages`
List programming languages used in a repository with byte counts.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |

**Returns:** Object mapping language names to byte counts (e.g., `{"Python": 52341, "Shell": 1200}`).
**Endpoint:** `GET /repos/{owner}/{repo}/languages`

---

### Tier 2: Issues (13 tools)

#### `github_create_issue`
Create a new issue in a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `title` | str | Yes | Issue title |
| `body` | str | No | Issue body (Markdown supported) |
| `assignees` | list[str] | No | List of usernames to assign |
| `labels` | list[str] | No | List of label names to apply |
| `milestone` | int | No | Milestone number to associate |

**Returns:** Created issue with number, id, title, html_url, state, user, labels, assignees, created_at.
**Endpoint:** `POST /repos/{owner}/{repo}/issues`

#### `github_get_issue`
Get a single issue by number.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |

**Returns:** Full issue object with number, title, body, state, user, labels, assignees, milestone, comments count, created_at, updated_at, closed_at.
**Endpoint:** `GET /repos/{owner}/{repo}/issues/{issue_number}`

#### `github_update_issue`
Update an existing issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `title` | str | No | New title |
| `body` | str | No | New body |
| `state` | str | No | New state: `open` or `closed` |
| `state_reason` | str | No | Reason for state change: `completed`, `not_planned`, `reopened` |
| `assignees` | list[str] | No | Replace assignees list |
| `labels` | list[str] | No | Replace labels list |
| `milestone` | int | No | Milestone number (null to remove) |

**Returns:** Updated issue object.
**Endpoint:** `PATCH /repos/{owner}/{repo}/issues/{issue_number}`

#### `github_list_issues`
List issues for a repository with optional filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `state` | str | No | Filter by state: `open`, `closed`, `all` (default `open`) |
| `assignee` | str | No | Filter by assignee username; `none` for unassigned; `*` for any |
| `labels` | str | No | Comma-separated label names (e.g., `bug,ui`) |
| `sort` | str | No | Sort by: `created`, `updated`, `comments` (default `created`) |
| `direction` | str | No | Sort direction: `asc` or `desc` (default `desc`) |
| `since` | str | No | Only issues updated after this ISO 8601 timestamp |
| `milestone` | str | No | Milestone number, `none`, or `*` |
| `creator` | str | No | Filter by issue creator username |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of issues with number, title, state, user, labels, assignees, created_at, updated_at.
**Endpoint:** `GET /repos/{owner}/{repo}/issues`

#### `github_add_issue_labels`
Add labels to an issue (does not remove existing labels).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `labels` | list[str] | Yes | Label names to add |

**Returns:** Updated list of all labels on the issue.
**Endpoint:** `POST /repos/{owner}/{repo}/issues/{issue_number}/labels`

#### `github_remove_issue_label`
Remove a single label from an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `label` | str | Yes | Label name to remove |

**Returns:** Updated list of remaining labels on the issue.
**Endpoint:** `DELETE /repos/{owner}/{repo}/issues/{issue_number}/labels/{name}`

#### `github_add_issue_assignees`
Add assignees to an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `assignees` | list[str] | Yes | List of usernames to add |

**Returns:** Updated issue object with new assignees.
**Endpoint:** `POST /repos/{owner}/{repo}/issues/{issue_number}/assignees`

#### `github_list_issue_comments`
List comments on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `since` | str | No | Only comments updated after this ISO 8601 timestamp |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of comments with id, body, user, created_at, updated_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/issues/{issue_number}/comments`

#### `github_create_issue_comment`
Create a comment on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `body` | str | Yes | Comment body (Markdown supported) |

**Returns:** Created comment with id, body, user, html_url, created_at.
**Endpoint:** `POST /repos/{owner}/{repo}/issues/{issue_number}/comments`

#### `github_update_issue_comment`
Update an existing issue comment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `comment_id` | int | Yes | Comment ID |
| `body` | str | Yes | New comment body (Markdown supported) |

**Returns:** Updated comment with id, body, user, html_url, updated_at.
**Endpoint:** `PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}`

#### `github_delete_issue_comment`
Delete an issue comment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `comment_id` | int | Yes | Comment ID |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/issues/comments/{comment_id}`

#### `github_lock_issue`
Lock an issue, restricting conversation to collaborators.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |
| `lock_reason` | str | No | Reason: `off-topic`, `too heated`, `resolved`, `spam` |

**Returns:** Confirmation of lock (204 No Content).
**Endpoint:** `PUT /repos/{owner}/{repo}/issues/{issue_number}/lock`

#### `github_unlock_issue`
Unlock an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `issue_number` | int | Yes | Issue number |

**Returns:** Confirmation of unlock (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/issues/{issue_number}/lock`

---

### Tier 3: Pull Requests (9 tools)

#### `github_list_pulls`
List pull requests for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `state` | str | No | Filter by state: `open`, `closed`, `all` (default `open`) |
| `head` | str | No | Filter by head branch (`user:ref-name` or `org:ref-name`) |
| `base` | str | No | Filter by base branch name |
| `sort` | str | No | Sort by: `created`, `updated`, `popularity`, `long-running` (default `created`) |
| `direction` | str | No | Sort direction: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of pull requests with number, title, state, user, head, base, created_at, updated_at, draft, merged_at.
**Endpoint:** `GET /repos/{owner}/{repo}/pulls`

#### `github_get_pull`
Get a single pull request by number.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |

**Returns:** Full PR object with number, title, body, state, user, head, base, mergeable, merged, draft, additions, deletions, changed_files, html_url, created_at, updated_at, merged_at.
**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}`

#### `github_create_pull`
Create a new pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `title` | str | Yes | PR title |
| `head` | str | Yes | The branch (or `user:branch`) containing changes |
| `base` | str | Yes | The branch to merge into |
| `body` | str | No | PR description (Markdown supported) |
| `draft` | bool | No | Create as draft PR (default false) |
| `maintainer_can_modify` | bool | No | Allow maintainer edits (default true) |

**Returns:** Created PR with number, title, html_url, state, draft, head, base, created_at.
**Endpoint:** `POST /repos/{owner}/{repo}/pulls`

#### `github_update_pull`
Update a pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `title` | str | No | New title |
| `body` | str | No | New body |
| `state` | str | No | New state: `open` or `closed` |
| `base` | str | No | New base branch |

**Returns:** Updated PR object.
**Endpoint:** `PATCH /repos/{owner}/{repo}/pulls/{pull_number}`

#### `github_merge_pull`
Merge a pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `commit_title` | str | No | Title for the merge commit |
| `commit_message` | str | No | Extra detail for the merge commit |
| `merge_method` | str | No | Merge method: `merge`, `squash`, or `rebase` (default `merge`) |
| `sha` | str | No | HEAD SHA to verify (ensures PR has not been updated) |

**Returns:** Merged status with sha, merged (bool), message.
**Endpoint:** `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`

#### `github_list_pull_reviews`
List reviews on a pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of reviews with id, user, body, state (APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED, PENDING), submitted_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews`

#### `github_create_pull_review`
Create a review on a pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `event` | str | Yes | Review action: `APPROVE`, `REQUEST_CHANGES`, or `COMMENT` |
| `body` | str | No | Review body text (required for `REQUEST_CHANGES` and `COMMENT`) |
| `comments` | list[dict] | No | Line-level comments: `[{"path": "file.py", "position": 5, "body": "comment"}]` |

**Returns:** Created review with id, user, state, body, submitted_at, html_url.
**Endpoint:** `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`

#### `github_list_pull_review_comments`
List review comments on a pull request (inline/diff comments).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `sort` | str | No | Sort by: `created`, `updated` (default `created`) |
| `direction` | str | No | Sort direction: `asc` or `desc` (default `desc`) |
| `since` | str | No | Only comments updated after this ISO 8601 timestamp |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of review comments with id, body, path, position, user, created_at, updated_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`

#### `github_list_pull_files`
List files changed in a pull request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `pull_number` | int | Yes | Pull request number |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of changed files with filename, status (added, removed, modified, renamed), additions, deletions, changes, patch.
**Endpoint:** `GET /repos/{owner}/{repo}/pulls/{pull_number}/files`

---

### Tier 4: Branches (5 tools)

#### `github_list_branches`
List branches in a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `protected` | bool | No | Filter to only protected branches |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of branches with name, commit sha, protected status.
**Endpoint:** `GET /repos/{owner}/{repo}/branches`

#### `github_get_branch`
Get details for a specific branch.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `branch` | str | Yes | Branch name |

**Returns:** Branch details with name, commit (sha, author, message, url), protected, protection_url.
**Endpoint:** `GET /repos/{owner}/{repo}/branches/{branch}`

#### `github_create_branch`
Create a new branch from a given SHA (via Git References API).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `branch` | str | Yes | New branch name |
| `sha` | str | Yes | SHA of the commit to branch from |

**Returns:** Created git reference with ref, node_id, url, object (sha, type).
**Endpoint:** `POST /repos/{owner}/{repo}/git/refs` (body: `{"ref": "refs/heads/{branch}", "sha": "{sha}"}`)

#### `github_delete_branch`
Delete a branch (via Git References API).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `branch` | str | Yes | Branch name to delete |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/git/refs/heads/{branch}`

#### `github_get_branch_protection`
Get branch protection rules for a branch.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `branch` | str | Yes | Branch name |

**Returns:** Protection rules including required_status_checks, enforce_admins, required_pull_request_reviews, restrictions, required_linear_history, allow_force_pushes, allow_deletions.
**Endpoint:** `GET /repos/{owner}/{repo}/branches/{branch}/protection`

---

### Tier 5: Commits (3 tools)

#### `github_list_commits`
List commits for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `sha` | str | No | Branch name or commit SHA to start listing from |
| `path` | str | No | Only commits containing this file path |
| `author` | str | No | Filter by commit author (GitHub username or email) |
| `committer` | str | No | Filter by committer (GitHub username or email) |
| `since` | str | No | Only commits after this ISO 8601 timestamp |
| `until` | str | No | Only commits before this ISO 8601 timestamp |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of commits with sha, commit (author, committer, message), author, committer, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/commits`

#### `github_get_commit`
Get a single commit by SHA.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `sha` | str | Yes | Commit SHA |

**Returns:** Full commit object with sha, commit (author, committer, message, tree), stats (additions, deletions, total), files (filename, status, additions, deletions, patch).
**Endpoint:** `GET /repos/{owner}/{repo}/commits/{sha}`

#### `github_compare_commits`
Compare two commits, branches, or tags.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `base` | str | Yes | Base commit SHA, branch, or tag |
| `head` | str | Yes | Head commit SHA, branch, or tag |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** Comparison with status (ahead, behind, diverged, identical), ahead_by, behind_by, total_commits, commits list, files list with diffs.
**Endpoint:** `GET /repos/{owner}/{repo}/compare/{base}...{head}`

---

### Tier 6: Releases (6 tools)

#### `github_list_releases`
List releases for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of releases with id, tag_name, name, body, draft, prerelease, created_at, published_at, html_url, assets.
**Endpoint:** `GET /repos/{owner}/{repo}/releases`

#### `github_get_release`
Get a single release by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `release_id` | int | Yes | Release ID |

**Returns:** Full release object with id, tag_name, name, body, draft, prerelease, author, assets, created_at, published_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/releases/{release_id}`

#### `github_create_release`
Create a new release.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `tag_name` | str | Yes | Tag name for the release (e.g., `v1.0.0`) |
| `name` | str | No | Release title |
| `body` | str | No | Release notes (Markdown supported) |
| `target_commitish` | str | No | Branch or commit SHA for the tag (default: default branch) |
| `draft` | bool | No | Create as draft (default false) |
| `prerelease` | bool | No | Mark as pre-release (default false) |
| `generate_release_notes` | bool | No | Auto-generate release notes (default false) |

**Returns:** Created release with id, tag_name, name, html_url, upload_url.
**Endpoint:** `POST /repos/{owner}/{repo}/releases`

#### `github_update_release`
Update an existing release.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `release_id` | int | Yes | Release ID |
| `tag_name` | str | No | New tag name |
| `name` | str | No | New release title |
| `body` | str | No | New release notes |
| `target_commitish` | str | No | New target branch or SHA |
| `draft` | bool | No | Update draft status |
| `prerelease` | bool | No | Update pre-release status |

**Returns:** Updated release object.
**Endpoint:** `PATCH /repos/{owner}/{repo}/releases/{release_id}`

#### `github_delete_release`
Delete a release.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `release_id` | int | Yes | Release ID |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/releases/{release_id}`

#### `github_list_release_assets`
List assets for a release.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `release_id` | int | Yes | Release ID |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of assets with id, name, label, content_type, size, download_count, browser_download_url, created_at.
**Endpoint:** `GET /repos/{owner}/{repo}/releases/{release_id}/assets`

---

### Tier 7: Actions / Workflows (6 tools)

#### `github_list_workflows`
List workflows in a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of workflows with id, name, path, state (active, disabled_manually, disabled_inactivity), created_at, updated_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/actions/workflows`

#### `github_list_workflow_runs`
List workflow runs, optionally filtered by workflow.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `workflow_id` | str | No | Workflow ID or filename (e.g., `ci.yml`) to filter by |
| `branch` | str | No | Filter by branch name |
| `event` | str | No | Filter by event type (e.g., `push`, `pull_request`) |
| `status` | str | No | Filter by status: `queued`, `in_progress`, `completed`, `action_required`, `cancelled`, `failure`, `neutral`, `skipped`, `stale`, `success`, `timed_out`, `waiting` |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of workflow runs with id, name, head_branch, head_sha, status, conclusion, event, html_url, created_at, updated_at, run_number.
**Endpoint:** `GET /repos/{owner}/{repo}/actions/runs` or `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs`

#### `github_get_workflow_run`
Get a single workflow run by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `run_id` | int | Yes | Workflow run ID |

**Returns:** Full run object with id, name, head_branch, head_sha, status, conclusion, event, workflow_id, html_url, created_at, updated_at, run_started_at, jobs_url, logs_url.
**Endpoint:** `GET /repos/{owner}/{repo}/actions/runs/{run_id}`

#### `github_trigger_workflow`
Trigger a workflow_dispatch event to run a workflow.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `workflow_id` | str | Yes | Workflow ID or filename (e.g., `deploy.yml`) |
| `ref` | str | Yes | Branch or tag to run the workflow on |
| `inputs` | dict | No | Input key-value pairs for workflow_dispatch inputs |

**Returns:** Confirmation (204 No Content on success). The workflow run is created asynchronously.
**Endpoint:** `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`

#### `github_cancel_workflow_run`
Cancel a workflow run.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `run_id` | int | Yes | Workflow run ID |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /repos/{owner}/{repo}/actions/runs/{run_id}/cancel`

#### `github_download_workflow_run_logs`
Get the download URL for workflow run logs.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `run_id` | int | Yes | Workflow run ID |

**Returns:** Redirect URL (302) to download a ZIP archive of log files. The tool returns the redirect URL as a string.
**Endpoint:** `GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs`

---

### Tier 8: Labels (4 tools)

#### `github_list_labels`
List labels for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of labels with id, name, description, color, default.
**Endpoint:** `GET /repos/{owner}/{repo}/labels`

#### `github_create_label`
Create a new label in a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `name` | str | Yes | Label name |
| `color` | str | Yes | Hex color code without `#` (e.g., `ff0000`) |
| `description` | str | No | Label description |

**Returns:** Created label with id, name, color, description.
**Endpoint:** `POST /repos/{owner}/{repo}/labels`

#### `github_update_label`
Update an existing label.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `label_name` | str | Yes | Current label name |
| `new_name` | str | No | New label name |
| `color` | str | No | New hex color code without `#` |
| `description` | str | No | New description |

**Returns:** Updated label object.
**Endpoint:** `PATCH /repos/{owner}/{repo}/labels/{label_name}`

#### `github_delete_label`
Delete a label from a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `label_name` | str | Yes | Label name to delete |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/labels/{label_name}`

---

### Tier 9: Milestones (4 tools)

#### `github_list_milestones`
List milestones for a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `state` | str | No | Filter by state: `open`, `closed`, `all` (default `open`) |
| `sort` | str | No | Sort by: `due_on`, `completeness` (default `due_on`) |
| `direction` | str | No | Sort direction: `asc` or `desc` (default `asc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of milestones with number, title, description, state, open_issues, closed_issues, due_on, created_at, updated_at, html_url.
**Endpoint:** `GET /repos/{owner}/{repo}/milestones`

#### `github_create_milestone`
Create a new milestone.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `title` | str | Yes | Milestone title |
| `description` | str | No | Milestone description |
| `due_on` | str | No | Due date as ISO 8601 timestamp (e.g., `2026-06-01T00:00:00Z`) |
| `state` | str | No | State: `open` or `closed` (default `open`) |

**Returns:** Created milestone with number, title, description, state, due_on, html_url.
**Endpoint:** `POST /repos/{owner}/{repo}/milestones`

#### `github_update_milestone`
Update an existing milestone.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `milestone_number` | int | Yes | Milestone number |
| `title` | str | No | New title |
| `description` | str | No | New description |
| `due_on` | str | No | New due date as ISO 8601 timestamp |
| `state` | str | No | New state: `open` or `closed` |

**Returns:** Updated milestone object.
**Endpoint:** `PATCH /repos/{owner}/{repo}/milestones/{milestone_number}`

#### `github_delete_milestone`
Delete a milestone.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | No | Repository owner (uses default) |
| `repo` | str | No | Repository name (uses default) |
| `milestone_number` | int | Yes | Milestone number |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /repos/{owner}/{repo}/milestones/{milestone_number}`

---

### Tier 10: Organizations (2 tools)

#### `github_list_orgs`
List organizations for the authenticated user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of organizations with login, id, description, url, avatar_url.
**Endpoint:** `GET /user/orgs`

#### `github_get_org`
Get details for a specific organization.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `org` | str | Yes | Organization login name |

**Returns:** Full org object with login, id, name, description, company, blog, location, email, public_repos, total_private_repos, html_url, created_at, updated_at.
**Endpoint:** `GET /orgs/{org}`

---

### Tier 11: Users (2 tools)

#### `github_get_authenticated_user`
Get the currently authenticated user's profile.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | | | Uses the configured token |

**Returns:** User profile with login, id, name, email, bio, public_repos, followers, following, html_url, created_at, updated_at.
**Endpoint:** `GET /user`

#### `github_get_user`
Get a user's public profile by username.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | str | Yes | GitHub username |

**Returns:** Public user profile with login, id, name, company, blog, location, email, bio, public_repos, followers, following, html_url, created_at, updated_at.
**Endpoint:** `GET /users/{username}`

---

### Tier 12: Search (4 tools)

> **Note:** Search API has a stricter rate limit of 30 requests/minute for authenticated users, except `github_search_code` which is limited to 9 requests/minute.

#### `github_search_repos`
Search for repositories.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | str | Yes | Search query with qualifiers (e.g., `tetris language:python stars:>100`) |
| `sort` | str | No | Sort by: `stars`, `forks`, `help-wanted-issues`, `updated` (default: best match) |
| `order` | str | No | Sort order: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** Search results with total_count, incomplete_results, and items list (repos with full_name, description, html_url, stargazers_count, language, topics, updated_at).
**Endpoint:** `GET /search/repositories`

#### `github_search_issues`
Search for issues and pull requests across repositories.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | str | Yes | Search query with qualifiers (e.g., `repo:owner/name is:open label:bug type:issue`) |
| `sort` | str | No | Sort by: `comments`, `reactions`, `reactions-+1`, `reactions--1`, `reactions-smile`, `reactions-thinking_face`, `reactions-heart`, `reactions-tada`, `interactions`, `created`, `updated` (default: best match) |
| `order` | str | No | Sort order: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** Search results with total_count, incomplete_results, and items list (issues/PRs with number, title, state, user, repository_url, html_url, labels, created_at, updated_at).
**Endpoint:** `GET /search/issues`

#### `github_search_code`
Search for code across repositories.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | str | Yes | Search query with qualifiers (e.g., `addClass in:file language:js repo:owner/name`) |
| `sort` | str | No | Sort by: `indexed` (default: best match) |
| `order` | str | No | Sort order: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** Search results with total_count, incomplete_results, and items list (code results with name, path, sha, html_url, repository (full_name)).
**Endpoint:** `GET /search/code`

#### `github_search_users`
Search for users.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | str | Yes | Search query with qualifiers (e.g., `tom language:python location:san+francisco`) |
| `sort` | str | No | Sort by: `followers`, `repositories`, `joined` (default: best match) |
| `order` | str | No | Sort order: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** Search results with total_count, incomplete_results, and items list (users with login, id, html_url, avatar_url, type).
**Endpoint:** `GET /search/users`

---

### Tier 13: Gists (5 tools)

#### `github_list_gists`
List gists for the authenticated user or a specified user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | str | No | GitHub username (default: authenticated user) |
| `since` | str | No | Only gists updated after this ISO 8601 timestamp |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of gists with id, description, public, files (names), html_url, created_at, updated_at.
**Endpoint:** `GET /gists` (authenticated user) or `GET /users/{username}/gists`

#### `github_create_gist`
Create a new gist.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | dict | Yes | Files as `{"filename.ext": {"content": "file contents"}}` |
| `description` | str | No | Gist description |
| `public` | bool | No | Whether gist is public (default false) |

**Returns:** Created gist with id, html_url, files, description, public, created_at.
**Endpoint:** `POST /gists`

#### `github_get_gist`
Get a single gist by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gist_id` | str | Yes | Gist ID |

**Returns:** Full gist object with id, description, public, files (with content), html_url, owner, created_at, updated_at, comments.
**Endpoint:** `GET /gists/{gist_id}`

#### `github_update_gist`
Update an existing gist.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gist_id` | str | Yes | Gist ID |
| `files` | dict | No | Files to update: `{"file.txt": {"content": "new"}}`, set to `null` to delete a file, or use `{"filename": "new_name.txt"}` to rename |
| `description` | str | No | New description |

**Returns:** Updated gist object.
**Endpoint:** `PATCH /gists/{gist_id}`

#### `github_delete_gist`
Delete a gist.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gist_id` | str | Yes | Gist ID |

**Returns:** Confirmation of deletion (204 No Content).
**Endpoint:** `DELETE /gists/{gist_id}`

---

### Tier 14: Stars (3 tools)

#### `github_list_starred_repos`
List repositories starred by the authenticated user or a specified user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | str | No | GitHub username (default: authenticated user) |
| `sort` | str | No | Sort by: `created`, `updated` (default `created`) |
| `direction` | str | No | Sort direction: `asc` or `desc` (default `desc`) |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of starred repositories with full repo details.
**Endpoint:** `GET /user/starred` (authenticated user) or `GET /users/{username}/starred`

#### `github_star_repo`
Star a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | Yes | Repository owner |
| `repo` | str | Yes | Repository name |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `PUT /user/starred/{owner}/{repo}`

#### `github_unstar_repo`
Unstar a repository.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | str | Yes | Repository owner |
| `repo` | str | Yes | Repository name |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `DELETE /user/starred/{owner}/{repo}`

---

### Tier 15: Notifications (2 tools)

#### `github_list_notifications`
List notifications for the authenticated user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `all` | bool | No | Include read notifications (default false, only unread) |
| `participating` | bool | No | Only notifications where user is directly participating (default false) |
| `since` | str | No | Only notifications updated after this ISO 8601 timestamp |
| `before` | str | No | Only notifications updated before this ISO 8601 timestamp |
| `per_page` | int | No | Results per page (default 30, max 100) |
| `page` | int | No | Page number (default 1) |

**Returns:** List of notifications with id, subject (title, url, type), reason, unread, updated_at, repository.
**Endpoint:** `GET /notifications`

#### `github_mark_notifications_read`
Mark notifications as read.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `last_read_at` | str | No | ISO 8601 timestamp; notifications updated before this are marked read (default: now) |

**Returns:** Confirmation (202 Accepted or 205 Reset Content).
**Endpoint:** `PUT /notifications`

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
While `PyGithub` and `ghapi` exist as Python GitHub SDKs, the project pattern uses direct `httpx` async HTTP calls. **Recommendation:** Use `httpx` (already a project dependency) for direct async HTTP calls, consistent with the ClickUp and Jira integration patterns.

### A2: Shared httpx Client with Bearer Auth
Create a shared `httpx.AsyncClient` with the Personal Access Token configured as a Bearer token.

```python
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    if not GITHUB_TOKEN:
        raise ToolError(
            "GITHUB_TOKEN is not configured. "
            "Set it in your environment or .env file."
        )
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
    return _client
```

**Lifecycle:** Same as ClickUp — process-scoped `AsyncClient`, cleaned up on exit. Acceptable for STDIO transport.

### A3: Default Owner/Repo Resolution
Optional config values `GITHUB_DEFAULT_OWNER` and `GITHUB_DEFAULT_REPO` reduce repetition for users who primarily work with a single repository. Every repo-scoped tool accepts `owner` and `repo` params with fallback to defaults.

```python
def _resolve_owner(owner: str | None = None) -> str:
    resolved = owner or GITHUB_DEFAULT_OWNER
    if not resolved:
        raise ToolError(
            "No owner provided. Either pass owner or set "
            "GITHUB_DEFAULT_OWNER in your environment."
        )
    return resolved

def _resolve_repo(repo: str | None = None) -> str:
    resolved = repo or GITHUB_DEFAULT_REPO
    if not resolved:
        raise ToolError(
            "No repo provided. Either pass repo or set "
            "GITHUB_DEFAULT_REPO in your environment."
        )
    return resolved
```

### A4: Tool Naming Convention
All GitHub tools prefixed with `github_` to distinguish from other integrations.

### A5: Error Handling
Same pattern as ClickUp: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. Rate limit responses (403 with `X-RateLimit-Remaining: 0`, or 429) include reset time in the error message. No automatic retry.

```python
async def _request(method: str, path: str, **kwargs) -> dict | list:
    client = _get_client()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"GitHub API request failed: {e}") from e

    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = response.headers.get("X-RateLimit-Reset", "unknown")
            raise ToolError(
                f"GitHub rate limit exceeded. Resets at Unix epoch: {reset}. "
                "Try again after the reset time."
            )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"GitHub secondary rate limit hit. Retry after: {retry_after}s."
        )
    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_msg = error_body.get("message", response.text)
        except Exception:
            error_msg = response.text
        raise ToolError(
            f"GitHub API error ({response.status_code}): {error_msg}"
        )
    if response.status_code == 204:
        return {}
    if response.status_code == 302:
        return {"redirect_url": response.headers.get("Location", "")}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}
```

### A6: Pagination
Tools return a single page of results. Callers can paginate via `page` and `per_page` parameters. No auto-pagination to keep response sizes bounded.

### A7: Response Format
Consistent JSON convention: `{"status": "success", "status_code": ..., ...}` matching existing patterns.

### A8: Missing Config Strategy
Same as ClickUp: register all tools regardless of configuration. Fail at invocation time with a clear `ToolError` if `GITHUB_TOKEN` is missing. Default owner/repo fail only when needed and not provided.

### A9: Workflow Logs Redirect Handling
The workflow logs endpoint returns a 302 redirect to a temporary download URL. The tool should use `follow_redirects=False` for this specific call and return the redirect URL, rather than downloading potentially large ZIP archives.

---

## Configuration Requirements

### Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `GITHUB_TOKEN` | Personal Access Token (classic or fine-grained) | Yes (at invocation) | `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `GITHUB_DEFAULT_OWNER` | Default repository owner (user or org) | No | `octocat` |
| `GITHUB_DEFAULT_REPO` | Default repository name | No | `hello-world` |

### Config Pattern
```python
GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
GITHUB_DEFAULT_OWNER: str | None = os.getenv("GITHUB_DEFAULT_OWNER")
GITHUB_DEFAULT_REPO: str | None = os.getenv("GITHUB_DEFAULT_REPO")
```

### Authentication Flow
1. User generates a Personal Access Token at `https://github.com/settings/tokens`
   - **Classic tokens:** Select scopes like `repo`, `workflow`, `gist`, `notifications`, `read:org`
   - **Fine-grained tokens:** Select specific repository access and permissions
2. Token is sent as `Authorization: Bearer {token}` header
3. httpx `AsyncClient` is configured once with this header

### Recommended Token Scopes (Classic)

| Scope | Required For |
|-------|-------------|
| `repo` | Full control of private repositories (issues, PRs, branches, commits, releases) |
| `workflow` | Triggering and managing GitHub Actions workflows |
| `gist` | Creating and managing gists |
| `notifications` | Reading and managing notifications |
| `read:org` | Reading organization membership |
| `delete_repo` | Deleting repositories (only if needed) |
| `user` | Reading user profile information |

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `GITHUB_TOKEN`, `GITHUB_DEFAULT_OWNER`, `GITHUB_DEFAULT_REPO` |
| `.env.example` | Modify | Add GitHub variables with descriptions |
| `src/mcp_toolbox/tools/github_tool.py` | **New** | All GitHub tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register github_tool |
| `tests/test_github_tool.py` | **New** | Tests for all GitHub tools |
| `CLAUDE.md` | Modify | Document GitHub integration |

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `respx` | httpx mock library (dev) | Yes |

No new runtime dependencies required.

---

## Testing Strategy

### Approach
Use `pytest` with `respx` for mocking HTTP calls, consistent with ClickUp and Jira test patterns.

```python
import respx

@respx.mock
async def test_list_issues():
    respx.get("https://api.github.com/repos/owner/repo/issues").mock(
        return_value=httpx.Response(200, json=[
            {"number": 1, "title": "Bug report", "state": "open"}
        ])
    )
    result = await server.call_tool("github_list_issues", {
        "owner": "owner", "repo": "repo"
    })
    assert "Bug report" in result
```

### Test Coverage
1. Happy path for every tool (75 tools)
2. Missing configuration (`GITHUB_TOKEN` not set) raises ToolError
3. Default owner/repo resolution (uses defaults when params omitted)
4. Default owner/repo error (no default, no param) raises ToolError
5. API errors: 401 Unauthorized, 403 Forbidden, 404 Not Found
6. Rate limiting: 403 with `X-RateLimit-Remaining: 0`, 429 with `Retry-After`
7. 204 No Content responses (delete, star, lock operations)
8. 302 redirect handling (workflow logs download)
9. Pagination parameter forwarding
10. Owner routing logic (authenticated user vs specific user vs org)

---

## Success Criteria

1. `uv sync` installs without errors (no new runtime deps needed)
2. All **75 GitHub tools** register and are discoverable via MCP Inspector
3. Tools return meaningful errors when `GITHUB_TOKEN` is missing
4. Default owner/repo fallback works correctly
5. All tools return consistent JSON responses (`{"status": "success", ...}`)
6. Rate limit errors include reset time information
7. New tests pass and full regression suite remains green
8. Total toolbox tool count reaches **413** (338 existing + 75 new)

---

## Tool Summary (75 tools total)

### Tier 1 -- Repositories (7 tools)
1. `github_list_repos` -- List repositories for authenticated user or specified user/org
2. `github_get_repo` -- Get repository details
3. `github_create_repo` -- Create a new repository (user or org)
4. `github_update_repo` -- Update repository settings
5. `github_delete_repo` -- Delete a repository
6. `github_list_repo_topics` -- List topics/tags for a repository
7. `github_list_repo_languages` -- List languages used in a repository

### Tier 2 -- Issues (13 tools)
8. `github_create_issue` -- Create a new issue
9. `github_get_issue` -- Get issue details by number
10. `github_update_issue` -- Update issue fields and state
11. `github_list_issues` -- List issues with filters (state, assignee, labels, etc.)
12. `github_add_issue_labels` -- Add labels to an issue
13. `github_remove_issue_label` -- Remove a label from an issue
14. `github_add_issue_assignees` -- Add assignees to an issue
15. `github_list_issue_comments` -- List comments on an issue
16. `github_create_issue_comment` -- Create a comment on an issue
17. `github_update_issue_comment` -- Update an existing issue comment
18. `github_delete_issue_comment` -- Delete an issue comment
19. `github_lock_issue` -- Lock an issue conversation
20. `github_unlock_issue` -- Unlock an issue conversation

### Tier 3 -- Pull Requests (9 tools)
21. `github_list_pulls` -- List pull requests with filters
22. `github_get_pull` -- Get pull request details
23. `github_create_pull` -- Create a new pull request
24. `github_update_pull` -- Update pull request title, body, state, or base
25. `github_merge_pull` -- Merge a pull request (merge, squash, or rebase)
26. `github_list_pull_reviews` -- List reviews on a pull request
27. `github_create_pull_review` -- Create a review (approve, request changes, comment)
28. `github_list_pull_review_comments` -- List inline review comments on a PR
29. `github_list_pull_files` -- List files changed in a pull request

### Tier 4 -- Branches (5 tools)
30. `github_list_branches` -- List branches in a repository
31. `github_get_branch` -- Get branch details including latest commit
32. `github_create_branch` -- Create a new branch from a SHA
33. `github_delete_branch` -- Delete a branch
34. `github_get_branch_protection` -- Get branch protection rules

### Tier 5 -- Commits (3 tools)
35. `github_list_commits` -- List commits with filters (author, path, date range)
36. `github_get_commit` -- Get commit details with file diffs
37. `github_compare_commits` -- Compare two commits, branches, or tags

### Tier 6 -- Releases (6 tools)
38. `github_list_releases` -- List releases
39. `github_get_release` -- Get release details
40. `github_create_release` -- Create a new release with tag
41. `github_update_release` -- Update release metadata
42. `github_delete_release` -- Delete a release
43. `github_list_release_assets` -- List assets attached to a release

### Tier 7 -- Actions / Workflows (6 tools)
44. `github_list_workflows` -- List workflows in a repository
45. `github_list_workflow_runs` -- List workflow runs with filters
46. `github_get_workflow_run` -- Get workflow run details
47. `github_trigger_workflow` -- Trigger a workflow_dispatch event
48. `github_cancel_workflow_run` -- Cancel a running workflow
49. `github_download_workflow_run_logs` -- Get download URL for run logs

### Tier 8 -- Labels (4 tools)
50. `github_list_labels` -- List repository labels
51. `github_create_label` -- Create a new label with color
52. `github_update_label` -- Update label name, color, or description
53. `github_delete_label` -- Delete a label

### Tier 9 -- Milestones (4 tools)
54. `github_list_milestones` -- List milestones with state and sort filters
55. `github_create_milestone` -- Create a new milestone
56. `github_update_milestone` -- Update milestone title, description, due date, state
57. `github_delete_milestone` -- Delete a milestone

### Tier 10 -- Organizations (2 tools)
58. `github_list_orgs` -- List organizations for authenticated user
59. `github_get_org` -- Get organization details

### Tier 11 -- Users (2 tools)
60. `github_get_authenticated_user` -- Get authenticated user profile
61. `github_get_user` -- Get public user profile by username

### Tier 12 -- Search (4 tools)
62. `github_search_repos` -- Search repositories with qualifiers
63. `github_search_issues` -- Search issues and PRs with qualifiers
64. `github_search_code` -- Search code across repositories
65. `github_search_users` -- Search users with qualifiers

### Tier 13 -- Gists (5 tools)
66. `github_list_gists` -- List gists for authenticated or specified user
67. `github_create_gist` -- Create a new gist
68. `github_get_gist` -- Get gist details with file contents
69. `github_update_gist` -- Update gist files and description
70. `github_delete_gist` -- Delete a gist

### Tier 14 -- Stars (3 tools)
71. `github_list_starred_repos` -- List starred repositories
72. `github_star_repo` -- Star a repository
73. `github_unstar_repo` -- Unstar a repository

### Tier 15 -- Notifications (2 tools)
74. `github_list_notifications` -- List notifications with filters
75. `github_mark_notifications_read` -- Mark all notifications as read
