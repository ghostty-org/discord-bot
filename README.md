# Ghostty Discord Bot

The Ghostty Discord Bot, humorlessly named "Ghostty Bot."

## Development

The Nix environment is the only supported development environment. You can
develop this without Nix, of course, but I'm not going to help you figure it
out.

### Discord Bot

You will have to [set up a Discord bot][discord-docs] and get a Discord
bot token. The instructions for that are out of scope for this README.
The Discord bot will require the following privileges:

- Manage Roles
- Members Privileged Intents

### Nix

Once your environment is set up, create a `.env` file based on `.env.example`
and run the app:

```console
$ python -m app
...
```

After you've made your changes, run the linter and formatter:

```console
ruff check
ruff format
```

### Non-Nix

This bot runs on Python 3.12+ and is managed with Poetry. To get started:

1. [Install poetry][poetry-docs] (preferably with [pipx]).
2. Create a `.env` file based on `.env.example`.
3. Install the project and run the bot:

   ```console
   $ poetry install
   ...
   $ poetry run python -m app
   ...
   ```

4. After you've made your changes, run the linter and formatter:

   ```console
   poetry run ruff check
   poetry run ruff format
   ```

[discord-docs]: https://discord.com/developers/applications
[poetry-docs]: https://python-poetry.org/docs/#installing-with-pipx
[pipx]: https://pipx.pypa.io/
