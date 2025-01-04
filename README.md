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
    - [Nix](#nix)
    - [Non-Nix](#non-nix)
- [Project structure](#project-structure)
- [Features](#features)
  - [`/docs`](#docs)
  - [Entity mentions](#entity-mentions)
  - [Message filters](#message-filters)
  - [Moving messages](#moving-messages)


# Bot setup

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
   * Use External Apps

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
* `#help`: a forum channel
* `#media`: a text channel
* `#showcase`: a text channel

The following roles will be necessary (both requiring the Manage Messages
permission):
* `mod`
* `helper`

## 4. Preparing the `.env` file

Create a `.env` file in the root of the project based on `.env.example`.
Below are explanations for each variable:
* channel/role IDs from [step 3](#3-preparing-a-discord-server):
  * `BOT_HELP_CHANNEL_ID`
  * `BOT_MEDIA_CHANNEL_ID`
  * `BOT_SHOWCASE_CHANNEL_ID`
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

> [!note]
> The Nix environment is the only supported development environment. You can
> develop this without Nix, of course, but I'm not going to help you figure it
> out.

### Nix

Run the bot with:
```console
$ python -m app
...
```

After you've made your changes, run the linter and formatter:
```console
$ ruff check
$ ruff format
```


### Non-Nix

This bot runs on Python 3.11+ and is managed with [Poetry]. To get started:
1. Install Poetry (e.g. via [uv] or [pipx]).
2. Install the project and run the bot:
   ```console
   $ poetry install
   ```
3. Run the bot:
   ```console
   $ poetry run python -m app
   ...
   ```
4. After you've made your changes, run the linter and formatter:
   ```console
   $ poetry run ruff check
   $ poetry run ruff format
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
  <img src="https://github.com/user-attachments/assets/0938881f-80ad-44d0-8414-915324f2761e" alt="/docs command message option" height="250px">
</p>

## Entity mentions

Automatic links to Ghostty's GitHub issues/PRs/discussions ("entities") when a
message contains GitHub-like mentions (`#1234`). It reacts to message edits and
deletions for 24 hours, while also providing a "🗑️ Delete" button for 30 seconds
in case of false positives. Mentioning entities in other repos is also supported
with prefixes:
* `web` for [ghostty-org/website][website-repo], e.g. `web#78`
* `bot` for [ghostty-org/discord-bot][bot-repo], e.g. `bot#98`
* `main` for [ghostty-org/ghostty][main-repo] (default), e.g. `main#2137` or
  just `#2137`

The bot also keeps a TTL-like cache to avoid looking up the same entity multiple
times (with data being refetched 30 minutes since last use), making the bot more
responsive (the example below can take ~3s on the first lookup and ~50µs on
subsequent lookups).

<img src="https://github.com/user-attachments/assets/aa899231-8ca0-4711-8c8b-2cfe5b6a98bb" alt="Entity mentions example" width="75%">


## Message filters

This feature takes care of keeping the `#showcase` and `#media` channels clean.
The bot will delete any message:
* without an attachment in `#showcase`
* without a link in `#media`

It will also DM users about the deletion and provide an explanation to make it
less confusing:

<img src="https://github.com/user-attachments/assets/263c59cb-19b5-4308-80d8-de464884692f" alt="Message filter notification" width="50%">

## Moving messages

TODO after [#112](https://github.com/ghostty-org/discord-bot/issues/112)


[bot-repo]: https://github.com/ghostty-org/discord-bot
[discord-docs]: https://discord.com/developers/applications
[discord-invite]: https://discord.gg/ghostty
[gh-new-token]: https://github.com/settings/tokens/new
[main-repo]: https://github.com/ghostty-org/ghostty
[pipx]: https://pipx.pypa.io/
[Poetry]: https://python-poetry.org/
[uv]: https://docs.astral.sh/uv/
[website-repo]: https://github.com/ghostty-org/website