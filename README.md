# Ghostty Discord Bot

The [Ghostty Discord][discord-invite] Bot, humorlessly named "Ghostty Bot."

It originally powered the invite system during Ghostty's private beta period,
successfully inviting ~5,000 people.
It now serves as the community's helper bot, making development discussion and
community moderation more efficient.

---

- [Bot setup](#bot-setup)
  - [1. Preparing a Discord application](#1-preparing-a-discord-application)
    - [1.1. Creating a Discord application](#11-creating-a-discord-application)
    - [1.2. Getting a Discord token](#12-getting-a-discord-token)
    - [1.3. Inviting the bot to your server](#13-inviting-the-bot-to-your-server)
  - [2. Getting a GitHub token](#2-getting-a-github-token)
  - [3. Preparing a Discord server](#3-preparing-a-discord-server)
  - [4. Preparing the `.env` file](#4-preparing-the-env-file)
  - [5. Running the bot](#5-running-the-bot)
- [Project structure](#project-structure)
- [Features](#features)
  - [`/docs`](#docs)
  - [`/close`](#close)
  - [Entity mentions](#entity-mentions)
  - [Message filters](#message-filters)
  - [Moving messages](#moving-messages)


# Bot setup

> [!warning]
> The bot is tailor-made for the Ghostty community and will most definitely be
> unsuitable for other servers. If you're looking to use similar features, you
> should consider looking for a more general-purpose bot, or forking this
> project and modifying it to suit your needs. That said, the core intent of
> this guide is to help contributors set up their development environment for
> building and testing new features. **Contributions are the goal, not
> standalone usage.**

## 1. Preparing a Discord application

### 1.1. Creating a Discord application

1. Go to the [Discord Developer Portal][discord-docs].
2. Click on the "New Application" button.
3. Pick a name for your bot.


### 1.2. Getting a Discord token

On your newly created bot's dashboard:
1. Go to "Bot" on the sidebar.
2. Click on the "Reset Token" button.
3. Save the newly generated token for later.
4. Under "Privileged Gateway Intents", enable:
   * Server Members Intent
   * Message Content Intent

### 1.3. Inviting the bot to your server
1. Go to "OAuth2" on the sidebar.
2. Under "OAuth2 URL Generator", select the `bot` scope.
3. Under "Bot Permissions" that appears, choose the following permissions:
   * Attach Files
   * Manage Messages
   * Manage Roles
   * Manage Threads
   * Manage Webhooks
   * Send Messages
   * Use External Apps\
   (your URL should contain a `1125917892061184` bitfield for `permissions`)
4. Use the generated URL at the bottom of the page to invite the bot to your
   server.


## 2. Getting a GitHub token

A GitHub token is necessary for the bot's Entity Mentions feature.

You can get one in two ways:
* On GitHub, go to Settings > Developer settings > Personal access tokens >
  Tokens (classic) > Generate new token, or use this link:
  [Generate new token][gh-new-token]. As the bot only accesses public
  repositories, it doesn't require any scopes.
* If you have the `gh` CLI installed and authenticated, run `gh auth token`.


## 3. Preparing a Discord server

The following channels will be necessary:
* `#help`: a forum channel with the following tags:
  * Moved to GitHub
  * Solved
  * Stale
  * Duplicate
* `#media`: a text channel
* `#showcase`: a text channel
* `#botlog-everything`: a log channel

The following roles will be necessary (both requiring the Manage Messages
permission):
* `mod`
* `helper`

## 4. Preparing the `.env` file

Create a `.env` file in the root of the project based on `.env.example`.
Below are explanations for each variable:
* `BOT_ACCEPT_INVITE_URL`: a URL to visit to accept the Ghostty invite
* channel/role IDs from [step 3](#3-preparing-a-discord-server):
  * `BOT_HELP_CHANNEL_ID`
  * `BOT_HELP_CHANNEL_TAG_IDS`: a comma-seperated list of `tag_name:tag_id`
    pairs. The tag names are `moved`, `solved`, `stale` and `duplicate`.
  * `BOT_MEDIA_CHANNEL_ID`
  * `BOT_SHOWCASE_CHANNEL_ID`
  * `BOT_LOG_CHANNEL_ID`
  * `BOT_MOD_ROLE_ID`
  * `BOT_HELPER_ROLE_ID`
* `BOT_TOKEN`: the Discord bot token from
  [step 1](#1-creating-a-discord-application).
* `GITHUB_ORG`: the GitHub organization name.
* `GITHUB_REPOS`: a comma-separated list of `prefix:repo_name` pairs used for
  entity mention prefixes. The `main`/`bot`/`web` prefixes aren't exactly fixed,
  but some of the bot logic assumes these names (e.g. defaulting to `main`).
* `GITHUB_TOKEN`: the GitHub token from [step 2](#2-getting-a-github-token).
* `SENTRY_DSN`: the Sentry DSN (optional).


## 5. Running the bot

This bot runs on Python 3.12 and is managed with [uv]. To get started:
1. Install [uv].
2. Run the bot:
   ```console
   $ uv run -m app
   ```
3. After you've made your changes, run the required checks:
   ```console
   $ uv run ruff check
   $ uv run ruff format
   $ uv run pyright app
   $ uv run taplo fmt pyproject.toml
   $ uv run pytest
   ```


# Project structure

<img src="https://github.com/user-attachments/assets/1a82433e-9f20-4189-a409-03cbc108a44c" alt="Project structure graph">

* `components/` is a place for all dedicated features, such as message filters
  or entity mentions. Most new features should become modules belonging to this
  package.
* `config.py` handles reading and parsing the environment variables and the
  local `.env` file. Although a standalone module, it's typically accessed
  through a `setup.py` re-export for brevity:
  ```diff
  -from app import config
  -from app.setup import bot
  +from app.setup import bot, config
  ```
* `core.py` loads the `components` package and houses the code for handling the
  most standard bot events (e.g. `on_ready`, `on_message`, `on_error`).
* `setup.py` creates the Discord and GitHub clients.
* `utils.py` contains utility functions not exactly tied to a specific feature.
* `__main__.py` initializes Sentry (optional) and starts the bot.


# Features

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

A command group to mark help channel posts as resolved, with various options for different resolution scenarios:

| Command            | Applied tag     | Argument                                  | Additional information                             |
| ------------------ | --------------- | ----------------------------------------- | -------------------------------------------------- |
| `/close solved`    | Solved          | Config option (optional)                  | Links to config documentation (if option provided) |
| `/close wontfix`   | Stale           | -                                         | Adds "WONTFIX" to post title                       |
| `/close stale`     | Stale           | -                                         | -                                                  |
| `/close moved`     | Moved to GitHub | GitHub entity number                      | Links to the GitHub entity                         |
| `/close duplicate` | Duplicate       | Help post ID/link or GitHub entity number | Links to original post or GitHub entity            |

## Entity mentions

Automatic links to Ghostty's GitHub issues/PRs/discussions ("entities") when a
message contains GitHub-like mentions (`#1234`). It reacts to message edits and
deletions for 24 hours, while also providing a "🗑️ Delete" button for 30 seconds
in case of false positives. Mentioning entities in other ghostty-org repos is
supported with prefixes:
* `web` for [ghostty-org/website][website-repo], e.g. `web#78`
* `bot` or `bobr` for [ghostty-org/discord-bot][bot-repo], e.g. `bot#98`
* `main` for [ghostty-org/ghostty][main-repo] (default), e.g. `main#2137` or
  just `#2137`

On top of that, any GitHub repository can be mentioned, either with
`owner/repo#1` (e.g. `astral-sh/uv#8020`), or `repo#1`, where the bot will
try finding the most popular repo with that name (e.g. `rust#105586`).

The bot also keeps a TTR cache to avoid looking up the same entity multiple
times (with data being refetched 30 minutes since last use), making the bot more
responsive (the example below can take ~2s on first lookup and ~5ms on
subsequent lookups).

<img src="https://github.com/user-attachments/assets/ce0df1f6-baac-43d7-9bee-1f2bdfda2ac4" alt="Entity mentions example" width="75%">


## Message filters

This feature takes care of keeping the `#showcase` and `#media` channels clean.
The bot will delete any message:
* without an attachment in `#showcase`
* without a link in `#media`

It will also DM users about the deletion and provide an explanation to make it
less confusing:

<img src="https://github.com/user-attachments/assets/2064111f-6e64-477c-b564-4034c5245adc" alt="Message filter notification" width="80%">

## Moving messages

Used for moving messages to more fitting channels (e.g. off-topic questions
in `#development` to `#tech`).

<img src="https://github.com/user-attachments/assets/e2e77e43-6200-4ab3-87ea-33e269e5a5cd" alt="Move message example" width="70%">

Ghostty troubleshooting questions can be turned into `#help` posts with a
related feature:

<img src="https://github.com/user-attachments/assets/9943a31c-3b0e-4606-99a0-5182ce114b87" alt="Turn into #help post example" width="70%">


[bot-repo]: https://github.com/ghostty-org/discord-bot
[discord-docs]: https://discord.com/developers/applications
[discord-invite]: https://discord.gg/ghostty
[gh-new-token]: https://github.com/settings/tokens/new
[main-repo]: https://github.com/ghostty-org/ghostty
[uv]: https://docs.astral.sh/uv/
[website-repo]: https://github.com/ghostty-org/website
