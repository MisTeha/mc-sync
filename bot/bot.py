"""
Discord bot for starting and stopping Minecraft servers on this VPS.

The easy way to use it is the control panel: one message with a Start/Stop button for each
server that keeps itself up to date, so it works from a phone without typing anything.
Post it once with /mc panel in the channel you want it in, then pin it.

  /mc panel             post the control panel in this channel (replaces the old one)
  /mc status            which servers exist and which are running
  /mc start <server>    start one (with exclusive: true, the others are stopped first)
  /mc stop <server>     stop one

Servers are discovered automatically: every folder in MC_ROOT that has a compose file.
The actual start/stop is done by ../vps/server.yml, so this bot is just a front end.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import tasks

MC_ROOT = Path(os.environ.get("MC_ROOT", "/opt/minecraft"))
PLAYBOOK_DIR = Path(os.environ.get("PLAYBOOK_DIR", "/opt/mc-sync/vps"))
ANSIBLE_PLAYBOOK = os.environ.get("ANSIBLE_PLAYBOOK", "ansible-playbook")
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
ALLOWED_ROLE = os.environ.get("ALLOWED_ROLE", "Minecraft Admin")  # needed for start/stop
# Where the panel's message ID and last action are remembered between restarts
PANEL_FILE = Path(os.environ.get("PANEL_FILE", Path(__file__).with_name("panel.json")))
# How often to re-check the servers, to catch changes made outside Discord
PANEL_REFRESH_SECONDS = int(os.environ.get("PANEL_REFRESH_SECONDS", "60"))

COMPOSE_FILES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")

# Discord allows 40 components per panel message; each server row uses 3 of them
MAX_PANEL_SERVERS = 10

# One start/stop at a time, so two people clicking at once can't trip over each other
busy = asyncio.Lock()
# While a playbook runs: (server, "Starting…"), shown on the panel
working: tuple[str, str] | None = None
# The server statuses the panel currently shows, so it's only edited when something changed
last_shown: dict[str, bool] | None = None


# ---- Helpers ----

def list_servers() -> list[str]:
    """Folder names in MC_ROOT that contain a compose file."""
    return sorted(
        folder.name
        for folder in MC_ROOT.iterdir()
        if folder.is_dir() and any((folder / name).exists() for name in COMPOSE_FILES)
    )


async def run(*args: str, cwd: Path) -> tuple[int, str]:
    """Run a command and return (exit code, combined output)."""
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await proc.communicate()
    return proc.returncode, output.decode(errors="replace")


async def is_running(server: str) -> bool:
    code, output = await run("docker", "compose", "ps", "--status", "running", "--quiet",
                             cwd=MC_ROOT / server)
    return code == 0 and output.strip() != ""


async def server_statuses() -> dict[str, bool]:
    """{server name: is it running}, checked in parallel."""
    names = list_servers()
    running = await asyncio.gather(*(is_running(name) for name in names))
    return dict(zip(names, running))


def busy_message() -> str:
    if working:
        server, doing = working
        return f"Busy: {doing.rstrip('…').lower()} **{server}**. Try again in a moment."
    return "Busy, try again in a moment."


def has_admin_role(user: discord.abc.User) -> bool:
    return isinstance(user, discord.Member) and any(role.name == ALLOWED_ROLE for role in user.roles)


def load_panel() -> dict:
    try:
        return json.loads(PANEL_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_panel():
    PANEL_FILE.write_text(json.dumps(panel))


# {"channel_id": ..., "message_id": ..., "last_action": "survival started by Alex <t:...:R>"}
panel = load_panel()


async def start_or_stop(server: str, action: str, user: discord.abc.User) -> tuple[bool, str]:
    """
    Run server.yml for one server and return (success, message for the user).
    The panel shows progress while it runs and the result afterwards.
    """
    global working
    if server not in list_servers():
        return False, f"Unknown server `{server}`."

    async with busy:
        working = (server, "Starting…" if action == "start" else "Stopping…")
        await refresh_panel()
        try:
            code, output = await run(
                ANSIBLE_PLAYBOOK, "server.yml", "-e", f"server={server}", "-e", f"action={action}",
                cwd=PLAYBOOK_DIR,
            )
        finally:
            working = None

    now = f"<t:{int(time.time())}:R>"  # Discord shows this as "2 minutes ago"
    verb = "started" if action == "start" else "stopped"
    if code == 0:
        panel["last_action"] = f"**{server}** {verb} by {user.display_name} {now}"
        message = f"✅ **{server}** {verb} by {user.display_name}."
    else:
        panel["last_action"] = f"❌ {user.display_name} couldn't {action} **{server}** {now}"
        message = f"❌ Couldn't {action} **{server}**. End of the playbook output:\n```\n{output[-1500:]}\n```"
    save_panel()
    await refresh_panel()
    return code == 0, message


# ---- Control panel ----

def build_panel(statuses: dict[str, bool]) -> ui.LayoutView:
    """The panel message: a card with one row per server, each with its own Start/Stop button."""
    view = ui.LayoutView(timeout=None)
    card = ui.Container(
        accent_colour=discord.Colour.green() if any(statuses.values()) else discord.Colour.dark_grey()
    )
    card.add_item(ui.TextDisplay("## Minecraft servers"))
    card.add_item(ui.Separator())

    for name, running in list(statuses.items())[:MAX_PANEL_SERVERS]:
        if working and working[0] == name:
            text = f"⏳ **{name}**\n-# {working[1]}"
        elif running:
            text = f"🟢 **{name}**\n-# Running"
        else:
            text = f"⚫ **{name}**\n-# Stopped"
        button = ServerButton("stop" if running else "start", name, disabled=working is not None)
        card.add_item(ui.Section(text, accessory=button))

    if not statuses:
        card.add_item(ui.TextDisplay(f"No servers found in `{MC_ROOT}`."))
    elif len(statuses) > MAX_PANEL_SERVERS:
        hidden = len(statuses) - MAX_PANEL_SERVERS
        card.add_item(ui.TextDisplay(f"-# …and {hidden} more. Use `/mc start` for those."))

    if panel.get("last_action"):
        card.add_item(ui.Separator())
        card.add_item(ui.TextDisplay(f"-# Last: {panel['last_action']}"))

    view.add_item(card)
    view.add_item(ui.ActionRow(RefreshButton()))
    return view


async def refresh_panel(statuses: dict[str, bool] | None = None):
    """Redraw the panel message. Does nothing if no panel has been posted."""
    global last_shown
    if not panel.get("message_id"):
        return
    if statuses is None:
        statuses = await server_statuses()
    try:
        channel = bot.get_channel(panel["channel_id"]) or await bot.fetch_channel(panel["channel_id"])
        await channel.get_partial_message(panel["message_id"]).edit(view=build_panel(statuses))
        last_shown = statuses
    except discord.NotFound:
        # Someone deleted the panel (or its channel): forget it until /mc panel is used again
        panel.pop("channel_id", None)
        panel.pop("message_id", None)
        save_panel()
    except discord.HTTPException as error:
        print(f"Couldn't update the panel: {error}")


# Buttons are "dynamic items": the bot recognises them by their ID (e.g. "mc:start:survival"),
# so they keep working after a restart without remembering anything about the message.

class ServerButton(ui.DynamicItem[ui.Button], template=r"mc:(?P<action>start|stop):(?P<server>.+)"):
    def __init__(self, action: str, server: str, disabled: bool = False):
        self.action = action
        self.server = server
        super().__init__(ui.Button(
            label="Start" if action == "start" else "Stop",
            style=discord.ButtonStyle.success if action == "start" else discord.ButtonStyle.danger,
            custom_id=f"mc:{action}:{server}",
            disabled=disabled,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["server"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if has_admin_role(interaction.user):
            return True
        await interaction.response.send_message(f"You need the **{ALLOWED_ROLE}** role for that.",
                                                ephemeral=True)
        return False

    async def callback(self, interaction: discord.Interaction):
        if busy.locked():
            await interaction.response.send_message(busy_message(), ephemeral=True)
            return

        if self.action == "stop":
            # Ask first, only visible to whoever clicked, so a stray tap can't kick everyone off
            await interaction.response.send_message(
                f"Stop **{self.server}**? Anyone playing on it will be disconnected.",
                view=ConfirmStop(self.server, interaction), ephemeral=True,
            )
            return

        await interaction.response.defer()  # acknowledges the click; the panel itself shows progress
        ok, message = await start_or_stop(self.server, "start", interaction.user)
        if not ok:
            await interaction.followup.send(message, ephemeral=True)


class RefreshButton(ui.DynamicItem[ui.Button], template=r"mc:refresh"):
    def __init__(self):
        super().__init__(ui.Button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary,
                                   custom_id="mc:refresh"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        global last_shown
        await interaction.response.defer()
        statuses = await server_statuses()
        await interaction.edit_original_response(view=build_panel(statuses))
        if interaction.message and interaction.message.id == panel.get("message_id"):
            last_shown = statuses


class ConfirmStop(ui.View):
    """The "Stop survival? [Yes, stop it] [Cancel]" prompt. Only the person who clicked sees it."""

    def __init__(self, server: str, asked: discord.Interaction):
        super().__init__(timeout=60)
        self.server = server
        self.asked = asked  # to edit the prompt if nobody answers

    @ui.button(label="Yes, stop it", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: ui.Button):
        self.stop()
        if busy.locked():
            await interaction.response.edit_message(content=busy_message(), view=None)
            return
        await interaction.response.edit_message(content=f"⏳ Stopping **{self.server}**…", view=None)
        ok, message = await start_or_stop(self.server, "stop", interaction.user)
        await interaction.edit_original_response(content=message)

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled, nothing was stopped.", view=None)

    async def on_timeout(self):
        try:
            await self.asked.edit_original_response(content="Timed out, nothing was stopped.", view=None)
        except discord.HTTPException:
            pass  # they dismissed the message already


@tasks.loop(seconds=PANEL_REFRESH_SECONDS)
async def keep_panel_fresh():
    """Catch changes made outside Discord: world push/pull scripts, Ansible by hand, crashes."""
    if busy.locked() or not panel.get("message_id"):
        return
    try:
        statuses = await server_statuses()
        if statuses != last_shown:
            await refresh_panel(statuses)
    except Exception as error:  # keep the loop alive whatever happens
        print(f"Panel refresh failed: {error!r}")


@keep_panel_fresh.before_loop
async def wait_for_login():
    await bot.wait_until_ready()


# ---- Slash commands ----

async def server_choices(interaction: discord.Interaction, current: str):
    """Autocomplete: the dropdown of servers shown while typing /mc start or /mc stop."""
    return [
        app_commands.Choice(name=name, value=name)
        for name in list_servers()
        if current.lower() in name.lower()
    ][:25]  # Discord's limit


mc = app_commands.Group(name="mc", description="Minecraft servers")


@mc.command(name="panel", description="Post the control panel in this channel (replaces the old one)")
@app_commands.checks.has_role(ALLOWED_ROLE)
async def post_panel(interaction: discord.Interaction):
    global last_shown
    await interaction.response.defer(ephemeral=True)
    statuses = await server_statuses()
    message = await interaction.channel.send(view=build_panel(statuses))

    old_channel_id, old_message_id = panel.get("channel_id"), panel.get("message_id")
    panel.update(channel_id=message.channel.id, message_id=message.id)
    save_panel()
    last_shown = statuses

    # Remove the previous panel so there's only ever one set of buttons
    if old_message_id:
        try:
            old_channel = bot.get_channel(old_channel_id) or await bot.fetch_channel(old_channel_id)
            await old_channel.get_partial_message(old_message_id).delete()
        except discord.HTTPException:
            pass

    await interaction.followup.send("Panel posted. Pin it so it's easy to find.", ephemeral=True)


@mc.command(description="Show which servers are running")
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    statuses = await server_statuses()
    lines = [f"{'🟢' if running else '⚫'} {name}" for name, running in statuses.items()]
    await interaction.followup.send("\n".join(lines) or f"No servers found in `{MC_ROOT}`.")


@mc.command(description="Start a Minecraft server")
@app_commands.describe(server="Which server to start")
@app_commands.autocomplete(server=server_choices)
@app_commands.checks.has_role(ALLOWED_ROLE)
async def start(interaction: discord.Interaction, server: str):
    if server not in list_servers():
        await interaction.response.send_message(f"Unknown server `{server}`.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)  # playbooks take a few seconds
    ok, message = await start_or_stop(server, "start", interaction.user)
    await interaction.followup.send(message)


@mc.command(description="Stop a Minecraft server")
@app_commands.describe(server="Which server to stop")
@app_commands.autocomplete(server=server_choices)
@app_commands.checks.has_role(ALLOWED_ROLE)
async def stop(interaction: discord.Interaction, server: str):
    if server not in list_servers():
        await interaction.response.send_message(f"Unknown server `{server}`.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    ok, message = await start_or_stop(server, "stop", interaction.user)
    await interaction.followup.send(message)


# ---- Bot setup ----

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Make panel buttons work, including on panels posted before a restart
        self.add_dynamic_items(ServerButton, RefreshButton)
        keep_panel_fresh.start()

        # Register the commands on your server only, so changes show up instantly
        guild = discord.Object(id=GUILD_ID)
        self.tree.add_command(mc, guild=guild)
        await self.tree.sync(guild=guild)


bot = Bot()


@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        message = f"You need the **{ALLOWED_ROLE}** role for that."
    else:
        message = f"Something went wrong: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
