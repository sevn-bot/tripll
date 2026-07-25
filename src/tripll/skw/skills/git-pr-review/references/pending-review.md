# Pending (draft) PR reviews via `gh`

A pending review holds inline comments that only the author sees until they submit.
Omitting `event` keeps it pending. Never submit on the human's behalf.

## Create

POST the review with comments and no `event`:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/reviews --input payload.json
```

`payload.json`:

```json
{
  "commit_id": "<pr head sha>",
  "body": "optional summary, shown only if submitted",
  "comments": [
    {"path": "dir/file.go", "line": 42, "side": "RIGHT", "body": "..."}
  ]
}
```

- No `event` field gives `state: "PENDING"`. `event` of `COMMENT`, `APPROVE`, or
  `REQUEST_CHANGES` publishes immediately — never set it on first post.
- `commit_id`: PR head SHA (`gh api repos/{owner}/{repo}/pulls/{pr} --jq .head.sha`).

## Anchor a comment

- `path` + `line` + `side`. `side` is `RIGHT` for added/context lines, `LEFT` for removed.
- `line` must fall inside a diff hunk or the call returns 422. Pull valid lines from patches:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/files --paginate
```

Added (`+`) and context lines on the new side are valid `RIGHT` anchors; removed lines are `LEFT`.

- Multi-line: add `start_line` (and `start_side`) alongside `line`.

## Suggested change

A comment body can carry a ` ```suggestion ` fenced block; GitHub replaces the
anchored line(s) in one click. Match anchor to replaced lines (`start_line`..`line`
for multi-line). Keep suggestions to a line or two.

## Verify it's a private draft

- `gh api repos/{owner}/{repo}/pulls/{pr}/reviews` → your review's `state` is `PENDING`.
- `gh api repos/{owner}/{repo}/pulls/{pr}/comments --paginate` must NOT contain your
  comments until submitted.
- Pending comments may report `line: null` and only a `position` until submitted. Expected.

## Edit or discard

- Replace all comments: delete the review and repost.
  `gh api -X DELETE repos/{owner}/{repo}/pulls/reviews/{review_id}`, then create again.
- One comment: `gh api -X PATCH repos/{owner}/{repo}/pulls/comments/{comment_id} -f body="..."`.
- Submitting and discarding happen in the author's Files-changed tab. Don't do either for them.

## Helper script

From the skill directory:

```bash
python3 scripts/post_pending_review.py <owner/repo> <pr_number> comments.json [--body "summary"]
```

Exits non-zero if the review is not a private `PENDING` draft.
