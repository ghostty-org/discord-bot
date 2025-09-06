import sentry_sdk

# Import bot from `core` instead of `setup` as core is otherwise never loaded.
from app.core import bot  # pyright: ignore[reportPrivateLocalImportUsage]
from app.setup import config

if config.sentry_dsn is not None:
    sentry_sdk.init(
        dsn=config.sentry_dsn.get_secret_value(),
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

# Our logging is handled by Loguru, and logs from the standard logging module are
# forwarded to Loguru in setup.py; hence, disable discord.py's log handler to avoid
# duplicated logs showing up in stderr.
bot.run(config.token.get_secret_value(), log_handler=None)
