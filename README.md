# Ghostty Discord Bot

The [Ghostty Discord][discord-invite] Bot, humorlessly named "Ghostty Bot."

It originally powered the invite system during Ghostty's private beta period,
successfully inviting ~5,000 people. It now serves as the community's helper
bot, making development discussion and community moderation more efficient.

For bot setup and project structure, see [CONTRIBUTING.md](CONTRIBUTING.md).

# Features

- [`/docs`](#docs)
- [`/close`](#close)
- [`#help` channel moderation](#help-channel-moderation)
- [Entity mentions](#entity-mentions)
  - [Code links](#code-links)
  - [Entity comments](#entity-comments)
  - [Commit mentions](#commit-mentions)
- [XKCD mentions](#xkcd-mentions)
- [Embed fixups](#embed-fixups)
- [Zig code blocks](#zig-code-blocks)
- [Message filters](#message-filters)
- [Moving messages](#moving-messages)

## `/docs`

A command for linking Ghostty documentation with autocomplete and an optional
message option:

<p align="center">
  <img src="https://github.com/user-attachments/assets/2cc0f7f0-8145-4dca-b7e6-5db18d939427" alt="/docs command autocomplete" height="250px">
  <img src="https://github.com/user-attachments/assets/9d97e37b-e31a-4664-9329-bb727fca3965" alt="/docs command message option" height="250px">
</p>

If a message is provided, a webhook will be used to send the message under the
interactor's server profile.

## `/close`

A command group to mark help channel posts as resolved, with various options for
different resolution scenarios:

| Command            | Applied tag     | Argument                                  | Additional information                             |
| ------------------ | --------------- | ----------------------------------------- | -------------------------------------------------- |
| `/close solved`    | Solved          | Config option (optional)                  | Links to config documentation (if option provided) |
| `/close wontfix`   | Stale           | -                                         | Adds "WON'T FIX" to post title                     |
| `/close upstream`  | Stale           | -                                         | Adds "UPSTREAM" to post title                      |
| `/close stale`     | Stale           | -                                         | -                                                  |
| `/close moved`     | Moved to GitHub | GitHub entity number                      | Links to the GitHub entity                         |
| `/close duplicate` | Duplicate       | Help post ID/link or GitHub entity number | Links to original post or GitHub entity            |

## `#help` channel moderation

Similar to [`/close`](#close), posts in the `#help` channel are automatically
closed after one day of inactivity when they have been marked as solved using
the post tags. Information about a `#help` channel scan is also published in the
bot log channel.

Bumps to old solved posts (older than one month) are also handled by warning the
user and locking the thread, to prevent often unrelated help requests in posts
that are no longer relevant.

## Entity mentions

Automatic links to Ghostty's GitHub issues/PRs/discussions ("entities") when a
message contains GitHub-like mentions (`#1234`). It reacts to message edits and
deletions for 24 hours, while also providing a "❌ Delete" button for 30 seconds
in case of false positives. A "❄️ Freeze" button is also provided to stop
reacting to message edits and deletions. Mentioning entities in other
ghostty-org repos is supported with prefixes:

- `web` or `website` for [ghostty-org/website][website-repo], e.g. `web#78`
- `bot`, `bobr`, or `discord-bot` for [ghostty-org/discord-bot][bot-repo], e.g.
  `bot#98`
- `main` or `ghostty` for [ghostty-org/ghostty][main-repo] (default), e.g.
  `main#2137` or just `#2137`

On top of that, any GitHub repository can be mentioned, either with
`owner/repo#1` (e.g. `astral-sh/uv#8020`), or `repo#1`, where the bot will try
finding the most popular repo with that name (e.g. `rust#105586`).

A full GitHub URL (such as `https://github.com/ghostty-org/ghostty/pull/4876`)
will also be responded to in a similar fashion, and the original GitHub embed
will be suppressed.

The bot also keeps a TTL cache to avoid looking up the same entity multiple
times (with data being refetched 30 minutes since last use), making the bot more
responsive (the example below can take ~2s on first lookup and ~5ms on
subsequent lookups).

<img src="https://github.com/user-attachments/assets/ce0df1f6-baac-43d7-9bee-1f2bdfda2ac4" alt="Entity mentions example" width="75%">

### Code links

Ghostty Bot responds to GitHub code range links with code blocks containing the
linked code. Same edit/delete hook and TTL cache rules apply.

<img src="https://github.com/user-attachments/assets/336b4a18-52c5-4ae6-9035-2a1f72856dfe" alt="Code links example" width="85%">

### Entity comments

Comments on issues, PRs, and discussions are displayed by the bot when linked. A
subset of GitHub events (e.g. "requested review", "closed the issue", "added
label") is also supported. Same edit/delete hook and TTL cache rules apply.

<img src="https://github.com/user-attachments/assets/217ef598-5fcb-4854-b2d6-a2b7d67435e8" alt="Entity comments example" width="65%">

### Commit mentions

Ghostty Bot responds to messages containing commit hashes (such as `b7913f0` or
`a8b9dd8dfc7a2cd6bb3f19969a450497654a47b0`) with information about the mentioned
commit. The same prefixes used for entity mentions is also supported by using an
`@`; e.g. `bot@4841da1`. Arbitrary repositories can also be mentioned with a
syntax similar to entity mentions; e.g. `python/cpython@2a6888e` or
`zig@39aca6f37e83e263236339f9`.

<img src="https://github.com/user-attachments/assets/c979dee7-ee0f-4ebf-82b3-f5d7e4ddbad9" alt="Commit mentions example" width="75%">

## XKCD mentions

Similar to the above feature, entity mentions with a prefix of `xkcd`, such as
`xkcd#1172`, will be replied to with an embed containing the XKCD's contents.
Message edits and deletion are also handled, and a "❌ Delete" button is provided
for one hour. A "❄️ Freeze" button is also provided to stop reacting to message
edits and deletions.

<img src="https://github.com/user-attachments/assets/ff1cf1c8-2927-4156-87af-aa5671252ee7" alt="XKCD mentions example" width="75%">

## Embed fixups

Ghostty Bot automatically fixes broken or missing embeds for social media links.
When a message contains a link to Reddit, X/Twitter, or Pixiv, the bot
suppresses the original embed and replies with a working alternative (using
[rxddit], [fixupx/fxtwitter], and [phixiv] respectively). Message edits and
deletion are also handled, with the standard buttons provided.

## Zig code blocks

Ghostty Bot looks for any code blocks with the language set to `zig` and
responds with custom `ansi` code blocks that contain correctly
syntax-highlighted Zig code (since Discord doesn't support Zig). Replies include
a dismiss button, plus:

- a **Freeze** button: stops the bot from reacting to edits/deletion of the
  original message (useful if the author wants to remove their unhighlighted
  code block but keep the bot's reply),
- a **Replace my message** button (for shorter messages only): deletes both the
  original and the bot's reply, then resends the original message via webhook as
  the original author, but with proper syntax highlighting.

The bot can also highlight Zig code in `.zig` attachments.

<img src="https://github.com/user-attachments/assets/a634482d-00fc-410f-a59d-ef4120ec66db" alt="Zig code blocks example" width="75%">

<sub>This feature relies on [trag1c/zig-codeblocks][zig-codeblocks-repo]!
^^</sub>

## Message filters

This feature takes care of keeping the `#showcase` and `#media` channels clean.
The bot will delete any message:

- without an attachment in `#showcase`
- without a link in `#media`

It will also DM users about the deletion and provide an explanation to make it
less confusing:

<img src="https://github.com/user-attachments/assets/2064111f-6e64-477c-b564-4034c5245adc" alt="Message filter notification" width="80%">

## Moving messages

Used for moving messages to more fitting channels (e.g. off-topic questions in
`#development` to `#tech`).

<img src="https://github.com/user-attachments/assets/e2e77e43-6200-4ab3-87ea-33e269e5a5cd" alt="Move message example" width="70%">

Ghostty troubleshooting questions can be turned into `#help` posts with a
related feature:

<img src="https://github.com/user-attachments/assets/9943a31c-3b0e-4606-99a0-5182ce114b87" alt="Turn into #help post example" width="70%">

The author of a message can also modify moved messages using an entry in the
context menu, which gives them the following:

- a **Delete** button: removes the moved message, without any further
  confirmation.
- an **Edit via modal** button: displays a text box to them that is pre-filled
  with the existing message content, allowing them to modify it almost like with
  the normal Discord edit option.
- an **Edit in thread** button: creates a new private thread in the current
  channel, adds them to it, then provides them with instructions on how to
  continue. In channels that don't support private threads, this button isn't
  shown.
- a **Help** button: displays information about both editing options to them.

If the message has one attachment, a "Remove attachment" button is also shown,
which removes the attachment without any further confirmation; if the message
has multiple attachments, a "Remove attachments" button is shown which provides
the user with a selection menu that allows them to select which attachments are
to be removed.

https://github.com/user-attachments/assets/8c8ed1cf-db00-414f-937f-43e565ae9d15

[bot-repo]: https://github.com/ghostty-org/discord-bot
[discord-invite]: https://discord.gg/ghostty
[fixupx/fxtwitter]: https://github.com/FxEmbed/FxEmbed
[main-repo]: https://github.com/ghostty-org/ghostty
[phixiv]: https://github.com/thelaao/phixiv
[rxddit]: https://github.com/MinnDevelopment/fxreddit
[website-repo]: https://github.com/ghostty-org/website
[zig-codeblocks-repo]: https://github.com/trag1c/zig-codeblocks
