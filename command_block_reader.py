# Command Block Reader — an Amulet Editor operation
# by Wizard Keen — https://github.com/wizard-keen/amulet-plugins (MIT licence)
# Finds every command block in the selection (or the whole dimension),
# reads its command, type, facing and settings, follows chains in run
# order, and writes a readable text report (plus optional JSON).
#
# Install: save this file into Amulet's  plugins/operations  folder,
# press the refresh button in the Operations tab, choose
# "Command Block Reader" and press Run Operation.
#
# Read-only: it never changes the world.

import os
import json
import time

from amulet.api.selection import SelectionGroup
from amulet.api.level import BaseLevel
from amulet.api.data_types import Dimension
from amulet.api.errors import ChunkDoesNotExist, ChunkLoadError

# ---------------- Settings you can change ----------------
BATCH_SIZE = 10               # chunks processed before freeing memory
SCAN_WHOLE_DIMENSION = False  # True = ignore the selection, scan every chunk
OUTPUT_FOLDER = ""            # "" = plugins\command_block_reports; or e.g. r"C:\Users\<you>\Desktop"
WRITE_JSON = True             # also write a .json version alongside the .txt
# ----------------------------------------------------------

TYPE_NAMES = {
    "command_block": "impulse",
    "chain_command_block": "chain",
    "repeating_command_block": "repeating",
}

# Bedrock stores facing as a number
BEDROCK_FACING = {0: "down", 1: "up", 2: "north", 3: "south", 4: "west", 5: "east"}

FACING_VECTORS = {
    "down": (0, -1, 0),
    "up": (0, 1, 0),
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "west": (-1, 0, 0),
    "east": (1, 0, 0),
}


# ---------------- NBT / property helpers ----------------
def _val(tag):
    """Turn an NBT tag into a plain Python value, across amulet_nbt versions."""
    if tag is None:
        return None
    for attr in ("py_str", "py_int", "py_float", "py_data", "value"):
        try:
            v = getattr(tag, attr)
        except Exception:
            continue
        if v is not None and not callable(v):
            return v
    return tag


def _compound(block_entity):
    """Get the root compound of a block entity's NBT."""
    if block_entity is None:
        return {}
    nbt = block_entity.nbt
    for attr in ("compound", "tag", "value"):
        try:
            c = getattr(nbt, attr)
        except Exception:
            continue
        if c is not None and hasattr(c, "get"):
            return c
    return nbt if hasattr(nbt, "get") else {}


def _nbt(comp, *names):
    for n in names:
        try:
            if n in comp:
                return _val(comp[n])
        except Exception:
            pass
    return None


def _prop(block, *names):
    props = block.properties
    for n in names:
        if n in props:
            return _val(props[n])
    return None


def _truthy(v):
    return v in (1, True, "1", "true", "True")


# ---------------- Reading one command block ----------------
def _describe(x, y, z, block, block_entity):
    comp = _compound(block_entity)

    raw_facing = _prop(block, "facing_direction", "minecraft:facing_direction", "facing")
    if isinstance(raw_facing, int) or (isinstance(raw_facing, str) and raw_facing.isdigit()):
        facing = BEDROCK_FACING.get(int(raw_facing), str(raw_facing))
    else:
        facing = str(raw_facing) if raw_facing is not None else "unknown"

    auto = _nbt(comp, "auto")
    return {
        "x": x,
        "y": y,
        "z": z,
        "type": TYPE_NAMES[block.base_name],
        "facing": facing,
        "conditional": _truthy(_prop(block, "conditional_bit", "conditional")),
        "always_active": _truthy(auto) if auto is not None else None,
        "tick_delay": _nbt(comp, "TickDelay"),
        "name": _nbt(comp, "CustomName") or "",
        "command": _nbt(comp, "Command") or "",
        "last_output": _nbt(comp, "LastOutput") or "",
    }


# ---------------- Chain following ----------------
def _next_pos(pos, facing):
    v = FACING_VECTORS.get(facing)
    if v is None:
        return None
    return (pos[0] + v[0], pos[1] + v[1], pos[2] + v[2])


def build_chains(found):
    """Group command blocks into chains, in the order they run.

    A chain block runs after whatever command block faces into it.
    Returns a list of (positions, is_loop) tuples.
    """
    fed = set()  # chain blocks that something faces into
    for pos, cb in found.items():
        nxt = _next_pos(pos, cb["facing"])
        if nxt in found and found[nxt]["type"] == "chain":
            fed.add(nxt)

    chains, visited = [], set()

    def walk(start):
        chain, p = [], start
        while p in found and p not in visited:
            visited.add(p)
            chain.append(p)
            nxt = _next_pos(p, found[p]["facing"])
            if nxt in found and found[nxt]["type"] == "chain":
                p = nxt
            else:
                break
        return chain

    # Chains start at any block nothing feeds into (impulse/repeating heads,
    # or chain blocks whose feeder is outside the scan)
    for start in sorted(found):
        if start not in fed and start not in visited:
            chains.append((walk(start), False))

    # Anything left over is part of a closed loop
    for start in sorted(found):
        if start not in visited:
            chains.append((walk(start), True))

    return chains


# ---------------- Selection helpers ----------------
def _boxes(selection):
    try:
        return list(selection)
    except Exception:
        return []


def _chunk_coords(boxes):
    coords = set()
    for b in boxes:
        for cx in range(b.min_x >> 4, ((b.max_x - 1) >> 4) + 1):
            for cz in range(b.min_z >> 4, ((b.max_z - 1) >> 4) + 1):
                coords.add((cx, cz))
    return coords


def _inside(boxes, x, y, z):
    for b in boxes:
        if b.min_x <= x < b.max_x and b.min_y <= y < b.max_y and b.min_z <= z < b.max_z:
            return True
    return False


# ---------------- Report writing ----------------
def _format_report(found, chains, info):
    lines = [
        "COMMAND BLOCK REPORT",
        "=" * 60,
        f"World:      {info['world']}",
        f"Dimension:  {info['dimension']}",
        f"Format:     {info['platform']} {info['version']}",
        f"Generated:  {info['time']}",
        f"Scanned {info['chunks']} chunks - found {len(found)} command blocks "
        f"in {len(chains)} chain(s)",
        "",
        "Facing = the direction the block's arrow points (where it passes to next).",
        "",
    ]
    for i, (chain, is_loop) in enumerate(chains, 1):
        title = f"CHAIN {i}  ({len(chain)} block{'s' if len(chain) != 1 else ''})"
        if is_loop:
            title += "  [LOOP]"
        lines += ["-" * 60, title, "-" * 60]
        for n, pos in enumerate(chain, 1):
            cb = found[pos]
            flags = []
            if cb["always_active"] is not None:
                flags.append("always active" if cb["always_active"] else "needs redstone")
            flags.append("conditional" if cb["conditional"] else "unconditional")
            if cb["tick_delay"]:
                flags.append(f"delay {cb['tick_delay']} ticks")
            lines.append(
                f"{n:>3}. {cb['type'].upper():<9} at ({cb['x']}, {cb['y']}, {cb['z']})  "
                f"facing {cb['facing']}  |  {', '.join(flags)}"
            )
            if cb["name"]:
                lines.append(f"     Name:    {cb['name']}")
            lines.append(f"     Command: {cb['command'] or '(empty)'}")
            if cb["last_output"]:
                lines.append(f"     Last output: {cb['last_output']}")
        lines.append("")
    if not found:
        lines.append("No command blocks found.")
    return "\n".join(lines)


# ---------------- The operation ----------------
def read_command_blocks(
    world: BaseLevel, dimension: Dimension, selection: SelectionGroup, options: dict
):
    platform = world.level_wrapper.platform
    version = world.level_wrapper.version
    boxes = _boxes(selection)

    if SCAN_WHOLE_DIMENSION or not boxes:
        chunk_list = sorted(world.all_chunk_coords(dimension))
        limit = None
    else:
        chunk_list = sorted(_chunk_coords(boxes))
        limit = boxes

    found = {}
    total = len(chunk_list)
    print(f"[Command Block Reader] Scanning {total} chunks in batches of {BATCH_SIZE}...")

    for start in range(0, total, BATCH_SIZE):
        for cx, cz in chunk_list[start:start + BATCH_SIZE]:
            try:
                chunk = world.get_chunk(cx, cz, dimension)
            except (ChunkDoesNotExist, ChunkLoadError):
                continue
            # Only block entities can be command blocks, so check those
            # rather than every block - much faster.
            for (x, y, z) in list(chunk.block_entities.keys()):
                if limit and not _inside(limit, x, y, z):
                    continue
                try:
                    block, block_entity = world.get_version_block(
                        x, y, z, dimension, (platform, version)
                    )
                except Exception:
                    continue
                if block.base_name in TYPE_NAMES:
                    found[(x, y, z)] = _describe(x, y, z, block, block_entity)

        # Free chunks we've finished with so memory stays low
        try:
            world.unload_unchanged()
        except Exception:
            pass

        done = min(start + BATCH_SIZE, total)
        yield done / total if total else 1.0

    chains = build_chains(found)

    world_name = getattr(world.level_wrapper, "level_name", None) or "world"
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in str(world_name)).strip()
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    folder = OUTPUT_FOLDER or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "command_block_reports",
    )
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"command_blocks_{safe_name}_{stamp}")

    info = {
        "world": world_name,
        "dimension": dimension,
        "platform": platform,
        "version": ".".join(str(v) for v in version) if isinstance(version, tuple) else version,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunks": total,
    }

    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(_format_report(found, chains, info))

    if WRITE_JSON:
        data = {
            "info": info,
            "chains": [
                {"loop": is_loop, "blocks": [found[p] for p in chain]}
                for chain, is_loop in chains
            ],
        }
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    print(f"[Command Block Reader] Found {len(found)} command blocks in {len(chains)} chain(s).")
    print(f"[Command Block Reader] Report saved to: {base}.txt")


export = {
    "name": "Command Block Reader",
    "operation": read_command_blocks,
}
