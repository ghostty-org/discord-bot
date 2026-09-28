from typing import TYPE_CHECKING, cast

from zig_codeblocks import CodeBlock, extract_codeblocks

if TYPE_CHECKING:
    from githubkit.typing import Missing
    from githubkit_schemas.latest.models import (
        PullRequestReviewComment,
        SimpleUser,
        WebhookPullRequestReviewCommentCreatedPropComment,
    )

__all__ = (
    "format_diff_note",
    "format_event_sender",
    "prettify_suggestions",
)


def format_diff_note(additions: int, deletions: int, changed_files: int) -> str | None:
    if not (changed_files and (additions or deletions)):
        return None  # Diff size unavailable
    return f"diff size: `+{additions}` `-{deletions}` ({changed_files} files changed)"


def prettify_suggestions(
    comment: PullRequestReviewComment
    | WebhookPullRequestReviewCommentCreatedPropComment,
) -> str | None:
    # We normalize CRLF to LF as GitHub used to use CRLF for comment bodies up until
    # some time in 2025, and we want to correctly handle both.
    body = comment.body.replace("\r\n", "\n")
    suggestions = [cb for cb in extract_codeblocks(body) if cb.lang == "suggestion"]
    if not suggestions:
        return None

    start = cast("int | None", comment.original_start_line)
    end = cast("int", comment.original_line)
    hunk_size = end - (end if start is None else start) + 1
    hunk_as_deleted_diff = "\n".join(
        ("-" + line[1:] if line[0] == "+" else line)
        for line in comment.diff_hunk.splitlines()[-hunk_size:]
    )

    for suggestion in suggestions:
        suggestion_as_added_diff = f"{hunk_as_deleted_diff}\n" + "\n".join(
            f"+{line}" for line in suggestion.body.splitlines()
        )
        body = body.replace(
            str(suggestion), str(CodeBlock("diff", suggestion_as_added_diff)), 1
        )
    return body


def format_event_sender(sender: Missing[SimpleUser]) -> str:
    return f"@{sender.login}" if sender else "?"
