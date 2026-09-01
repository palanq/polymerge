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

import argparse, asyncio, os

import discord


async def fetch(http, app_id, guild_id):
    if guild_id is None:
        return await http.get_global_commands(app_id)
    return await http.get_guild_commands(app_id, guild_id)


async def wipe(http, app_id, guild_id):
    """Overwrite a scope's command set with the empty list.

    These are the same PUT endpoints CommandTree.sync uses, which is what makes
    a sync a bulk *replace* rather than an addition -- and why a global set
    heals itself on the next sync while a guild set, which nothing else writes,
    does not."""
    if guild_id is None:
        return await http.bulk_upsert_global_commands(app_id, [])
    return await http.bulk_upsert_guild_commands(app_id, guild_id, [])


async def run(args):
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("set DISCORD_TOKEN in the environment")

    # Driven through the HTTP layer rather than a CommandTree, deliberately.
    # A tree needs Client.application_id, which is a read-only property fed by
    # the gateway -- so a login-only script cannot set it and sync() raises
    # MissingApplicationID. Listing and clearing are pure REST anyway; there is
    # no local tree to sync, only a remote set to read and overwrite.
    #
    # No intents: this never touches the gateway's message stream.
    client = discord.Client(intents=discord.Intents.none())
    guild_id = args.guild or args.clear_guild

    async with client:
        await client.login(token)
        app = await client.application_info()
        http, app_id = client.http, app.id
        print(f"application: {app.name} ({app_id})\n")

        if args.clear_global or args.clear_guild:
            target = None if args.clear_global else args.clear_guild
            scope = "globally" if target is None else f"guild {target}"
            before = await fetch(http, app_id, target)
            names = ", ".join("/" + c["name"] for c in before)
            print(f"{scope}: {len(before)} registered ({names or 'none'})")
            if not before:
                print("nothing to clear")
                return
            if not args.yes:
                # Registered commands are shared with everyone using the bot, so
                # this is not a local change -- confirm before making it.
                print(f"\nThis removes all {len(before)} from {scope}. "
                      f"Re-run with --yes to do it.")
                return
            await wipe(http, app_id, target)
            print(f"cleared; {scope} now has 0 registered")
            if target is None:
                print("Restart the bot to re-register from the tree.")
            else:
                print("Global commands are untouched and still apply here.")
        else:
            scopes = [("global", None)]
            if guild_id:
                scopes.append((f"guild {guild_id}", guild_id))
            for scope, g in scopes:
                cmds = await fetch(http, app_id, g)
                print(f"{scope}: {len(cmds)} registered")
                for c in cmds:
                    print(f"    /{c['name']}  --  {c.get('description', '')}")


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
