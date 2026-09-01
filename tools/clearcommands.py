"""List or clear an application's registered slash commands.

Renaming a slash command leaves the old name registered on Discord's side, and
whether it goes away on its own depends on the scope:

- **Global** sets heal themselves. `tree.sync()` is a bulk *overwrite* (Discord's
  PUT endpoint), so the next global sync replaces the whole set with whatever
  the tree holds and a removed name simply stops existing. Running polybot once
  with POLYMERGE_DEV_GUILD unset is all that is needed.
- **Guild** sets do not, because a guild's commands are a separate set from the
  global ones. `copy_global_to` writes a second copy into the guild, so a guild
  that has ever been dev-synced keeps showing whatever was in the tree at the
  time -- alongside the global set, which is what produces duplicate and stale
  entries in the picker.

This clears either. It is a maintenance action rather than bot behaviour, so it
lives here instead of growing a flag on polybot: tools/ is never shipped (the
Dockerfile copies only polybot.py, polymerge.py, Overlays/ and Assets/) and
nothing imports it.

    python tools/clearcommands.py --list
    python tools/clearcommands.py --list --guild 123456789012345678
    python tools/clearcommands.py --clear-guild 123456789012345678
    python tools/clearcommands.py --clear-global

DISCORD_TOKEN selects the application, so point it at the *beta* bot's token to
tidy the beta bot. Clearing does not touch prefix commands, which are not
registered with Discord at all -- `!merge` keeps working throughout.
"""

import argparse, asyncio, os, sys

import discord
from discord import app_commands


async def run(args):
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("set DISCORD_TOKEN in the environment")

    # No intents needed: this only touches the application command endpoints,
    # never the gateway's message stream.
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    where = discord.Object(id=args.guild or args.clear_guild) \
        if (args.guild or args.clear_guild) else None

    async with client:
        await client.login(token)
        # login() alone does not populate application_id on every path, and the
        # command endpoints need it.
        app = await client.application_info()
        client.application_id = app.id
        tree.client.application_id = app.id

        if args.clear_global or args.clear_guild:
            scope = f"guild {where.id}" if args.clear_guild else "globally"
            before = await tree.fetch_commands(guild=where)
            print(f"{scope}: {len(before)} registered "
                  f"({', '.join('/' + c.name for c in before) or 'none'})")
            if not before:
                print("nothing to clear")
                return
            if not args.yes:
                # Registered commands are shared with everyone using the bot, so
                # this is not a local change -- confirm before making it.
                print(f"\nThis removes all {len(before)} from {scope}. "
                      f"Re-run with --yes to do it.")
                return
            tree.clear_commands(guild=where)
            await tree.sync(guild=where)
            print(f"cleared; {scope} now has 0 registered")
            if args.clear_guild:
                print("Global commands are untouched and still apply here.")
        else:
            for scope, g in (("global", None),
                             *([(f"guild {where.id}", where)] if where else [])):
                cmds = await tree.fetch_commands(guild=g)
                print(f"{scope}: {len(cmds)} registered")
                for c in cmds:
                    print(f"    /{c.name}  --  {c.description}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true",
                   help="show what is registered (the default)")
    p.add_argument("--guild", type=int, metavar="ID",
                   help="also list this guild's own command set")
    p.add_argument("--clear-guild", type=int, metavar="ID",
                   help="remove every command registered to this guild")
    p.add_argument("--clear-global", action="store_true",
                   help="remove every globally registered command")
    p.add_argument("--yes", action="store_true",
                   help="actually perform a --clear-* (they dry-run otherwise)")
    args = p.parse_args()
    if args.clear_global and args.clear_guild:
        raise SystemExit("pick one scope at a time")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
