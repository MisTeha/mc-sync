#!/usr/bin/env python3
"""
Carry player data (inventory, position, XP, advancements, stats) correctly when a world
moves between singleplayer and a dedicated server.

Why this is needed: singleplayer treats the host player differently from everyone else.
  - Up to 1.21.x: the host's data lives in level.dat (Data.Player), and it overrides the
    host's own playerdata/<uuid>.dat file.
  - 26.1 and later: player files moved to players/data/<uuid>.dat, and level.dat only
    holds Data.singleplayer_uuid, pointing at the host's file.
A dedicated server ignores both and only uses the per-player files. LAN guests are
always stored as per-player files, so they move like server players do.

  players.py push <incoming_world> <server_world>
      Before an uploaded singleplayer world replaces the server's world:
        - the uploader (the singleplayer host) gets their singleplayer data on the server
        - every other player: the newer copy wins, and players that only exist on
          the server are kept, so nobody's inventory is lost

  players.py pull <server_world> <archive> <player_uuid>
      Pack the server's world so that <player_uuid> is the singleplayer host,
      with their server inventory. Everyone else's files come along unchanged.
"""

import shutil
import struct
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

import nbtlib
from nbtlib import Compound, File, IntArray

# Where each kind of per-player file lives, in the old and the new (26.1+) world format
OLD_LAYOUT = {"data": "playerdata", "advancements": "advancements", "stats": "stats"}
NEW_LAYOUT = {"data": "players/data", "advancements": "players/advancements", "stats": "players/stats"}
EXTENSION = {"data": ".dat", "advancements": ".json", "stats": ".json"}


# ---- Small helpers ----

def is_new_format(world: Path, level: File) -> bool:
    return "singleplayer_uuid" in level["Data"] or (world / "players").is_dir()


def layout_of(world: Path, level: File) -> dict:
    return NEW_LAYOUT if is_new_format(world, level) else OLD_LAYOUT


def uuid_from_ints(ints) -> str:
    """Minecraft stores UUIDs in NBT as 4 signed 32-bit ints."""
    return str(uuid.UUID(bytes=struct.pack(">4i", *(int(i) for i in ints))))


def ints_from_uuid(value: str) -> IntArray:
    return IntArray(struct.unpack(">4i", uuid.UUID(value).bytes))


def player_file(world: Path, layout: dict, kind: str, player: str) -> Path:
    return world / layout[kind] / f"{player}{EXTENSION[kind]}"


def existing_files(world: Path, layout: dict, player: str) -> dict:
    """{kind: path} for the files this player has in this world."""
    files = {kind: player_file(world, layout, kind, player) for kind in layout}
    return {kind: path for kind, path in files.items() if path.exists()}


def players_in(world: Path, layout: dict) -> set:
    """UUIDs of every player that has any file in this world."""
    found = set()
    for kind, folder in layout.items():
        for path in (world / folder).glob(f"*{EXTENSION[kind]}"):
            try:
                found.add(str(uuid.UUID(path.stem)))
            except ValueError:
                pass  # not a player file
    return found


def newest(files: dict) -> float:
    return max(path.stat().st_mtime for path in files.values())


def warn_if_offline_mode(server_world: Path):
    properties = server_world.parent / "server.properties"
    if properties.exists() and "online-mode=false" in properties.read_text():
        print("WARNING: the server has online-mode=false, so its player UUIDs differ from your "
              "Minecraft account's UUID. Inventories won't line up between singleplayer and the server.")


# ---- push: singleplayer world -> server ----

def host_of(world: Path, level: File) -> str | None:
    """The singleplayer host's UUID, or None if the world has no host recorded."""
    data = level["Data"]
    if "singleplayer_uuid" in data:
        return uuid_from_ints(data["singleplayer_uuid"])
    if "Player" in data and "UUID" in data["Player"]:
        return uuid_from_ints(data["Player"]["UUID"])
    return None


def push(incoming: Path, server_world: Path):
    level = nbtlib.load(incoming / "level.dat")
    layout = layout_of(incoming, level)
    host = host_of(incoming, level)

    # 1. The host. In the old format their real data is in level.dat, so write it out as
    #    their per-player file, which is what the server reads. In the new format it
    #    already is a per-player file.
    if host is None:
        print("No singleplayer host in this world; per-player files are used as they are.")
    elif not is_new_format(incoming, level):
        target = player_file(incoming, layout, "data", host)
        target.parent.mkdir(parents=True, exist_ok=True)
        File(level["Data"]["Player"], gzipped=True).save(target)
        print(f"{host}: you (singleplayer host), inventory taken from level.dat")
    else:
        print(f"{host}: you (singleplayer host), inventory taken from your upload")

    # 2. Everyone else on the server: keep whichever copy is newer.
    if not (server_world / "level.dat").exists():
        print("The server has no world yet, so there are no server players to keep.")
        return
    warn_if_offline_mode(server_world)
    server_layout = layout_of(server_world, nbtlib.load(server_world / "level.dat"))

    for player in sorted(players_in(server_world, server_layout) - {host}):
        on_server = existing_files(server_world, server_layout, player)
        uploaded = existing_files(incoming, layout, player)

        if uploaded and newest(uploaded) >= newest(on_server):
            print(f"{player}: kept the uploaded copy (it's newer, e.g. from a LAN session)")
            continue

        for path in uploaded.values():
            path.unlink()
        for kind, source in on_server.items():
            target = player_file(incoming, layout, kind, player)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)  # copy2 keeps the modification time
        print(f"{player}: kept the server's copy" + (" (it's newer)" if uploaded else " (wasn't in the upload)"))

    for player in sorted(players_in(incoming, layout) - players_in(server_world, server_layout) - {host}):
        print(f"{player}: new on the server (from the upload, e.g. a LAN guest)")


# ---- pull: server world -> singleplayer ----

def pull(server_world: Path, archive: Path, player: str):
    player = str(uuid.UUID(player))  # normalises "abcd..." and "ab-cd-..." forms
    level = nbtlib.load(server_world / "level.dat")
    layout = layout_of(server_world, level)
    data = level["Data"]
    player_dat = player_file(server_world, layout, "data", player)

    # Make `player` the singleplayer host. Without this, the old format would load whatever
    # stale Player tag is in level.dat (possibly someone else's) instead of their inventory.
    if is_new_format(server_world, level):
        data["singleplayer_uuid"] = ints_from_uuid(player)
    elif player_dat.exists():
        data["Player"] = Compound(nbtlib.load(player_dat))
    else:
        data.pop("Player", None)  # never been on the server: start fresh in singleplayer

    if player_dat.exists():
        print(f"{player}: you'll be the singleplayer host, with your server inventory")
    else:
        print(f"{player}: you haven't played on this server, so you'll start fresh at spawn")

    # Pack the world with the edited level.dat. The live level.dat is never changed.
    # level.dat_old is left out so a stale host can't come back from it; session.lock isn't needed.
    skip = {"level.dat", "level.dat_old", "session.lock"}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        edited_level = Path(tmp) / "level.dat"
        level.save(edited_level)
        for path in sorted(server_world.iterdir()):
            if path.name not in skip:
                tar.add(path, arcname=path.name)
        tar.add(edited_level, arcname="level.dat")
    print(f"Packed {server_world} -> {archive}")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["push", incoming, server_world]:
            push(Path(incoming), Path(server_world))
        case ["pull", server_world, archive, player]:
            pull(Path(server_world), Path(archive), player)
        case _:
            sys.exit(__doc__)
