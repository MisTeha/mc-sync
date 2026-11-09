"""
Discord bot for starting and stopping Minecraft servers on this VPS.

  /mc status            which servers exist and which are running
  /mc start <server>    start one (with exclusive: true, the others are stopped first)
  /mc stop <server>     stop one

Servers are discovered automatically: every folder in MC_ROOT that has a compose file.
The actual start/stop is done by ../vps/server.yml, so this bot is just a front end.
"""

import asyncio
import os
from pathlib import Path

import discord
from discord import app_commands

MC_ROOT = Path(os.environ.get("MC_ROOT", "/opt/minecraft"))
PLAYBOOK_DIR = Path(os.environ.get("PLAYBOOK_DIR", "/opt/mc-sync/vps"))
ANSIBLE_PLAYBOOK = os.environ.get("ANSIBLE_PLAYBOOK", "ansible-playbook")
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])
ALLOWED_ROLE = os.environ.get("ALLOWED_ROLE", "Minecraft Admin")  # needed for start/stop

COMPOSE_FILES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")

# One start/stop at a time, so two people clicking at once can't trip over each other
busy = asyncio.Lock()


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


async def server_choices(interaction: discord.Interaction, current: str):
    """Autocomplete: the dropdown of servers shown while typing /mc start or /mc stop."""
    return [
        app_commands.Choice(name=name, value=name)
        for name in list_servers()
        if current.lower() in name.lower()
    ][:25]  # Discord's limit


async def start_or_stop(interaction: discord.Interaction, server: str, action: str):
    if server not in list_servers():
        await interaction.response.send_message(f"Unknown server `{server}`.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)  # playbooks take a few seconds
    async with busy:
        code, output = await run(
            ANSIBLE_PLAYBOOK, "server.yml", "-e", f"server={server}", "-e", f"action={action}",
            cwd=PLAYBOOK_DIR,
        )

    if code == 0:
        verb = "started" if action == "start" else "stopped"
        await interaction.followup.send(f"✅ **{server}** {verb} by {interaction.user.display_name}.")
    else:
        await interaction.followup.send(
            f"❌ Couldn't {action} **{server}**. End of the playbook output:\n```\n{output[-1500:]}\n```"
        )


# ---- Slash commands ----

mc = app_commands.Group(name="mc", description="Minecraft servers")


@mc.command(description="Show which servers are running")
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    lines = [f"{'🟢' if await is_running(name) else '⚫'} {name}" for name in list_servers()]
    await interaction.followup.send("\n".join(lines) or f"No servers found in `{MC_ROOT}`.")


@mc.command(description="Start a Minecraft server")
@app_commands.describe(server="Which server to start")
@app_commands.autocomplete(server=server_choices)
@app_commands.checks.has_role(ALLOWED_ROLE)
async def start(interaction: discord.Interaction, server: str):
    await start_or_stop(interaction, server, "start")


@mc.command(description="Stop a Minecraft server")
@app_commands.describe(server="Which server to stop")
@app_commands.autocomplete(server=server_choices)
@app_commands.checks.has_role(ALLOWED_ROLE)
async def stop(interaction: discord.Interaction, server: str):
    await start_or_stop(interaction, server, "stop")


# ---- Bot setup ----

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
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


bot.run(os.environ["DISCORD_TOKEN"])
