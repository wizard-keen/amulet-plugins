# NPC Reader — an Amulet Editor operation for Bedrock worlds
# by Wizard Keen — https://github.com/wizard-keen/amulet-plugins (MIT licence)
#
# Finds every NPC in the selection (or the whole dimension if nothing is
# selected) and writes a report with each NPC's position, facing, dialogue,
# buttons and the commands they run. Any function an NPC calls is looked up
# in the world's behaviour packs and its contents are printed underneath.
#
# Bedrock only. Amulet's normal entity loading doesn't see Bedrock entities,
# so this reads the world's database directly. It never changes the world.
#
# Install: save into Amulet's plugins/operations folder, restart Amulet,
# choose "NPC Reader" in the Operations tab and press Run Operation.

import os
import re
import json
import math
import struct
import time

from amulet.api.selection import SelectionGroup
from amulet.api.level import BaseLevel
from amulet.api.data_types import Dimension

import amulet_nbt

VERSION = "1.1"

# ---------------- Settings you can change ----------------
BATCH_SIZE = 50               # chunks per progress step
OUTPUT_FOLDER = ""            # "" = plugins\npc_reports; or e.g. r"C:\Users\<you>\Desktop"
WRITE_JSON = True             # also write a .json version alongside the .txt
FUNCTION_DEPTH = 3            # how deep to follow functions that call other functions
LIST_ALL_FUNCTIONS = True     # add an appendix with every function in the behaviour packs
EXTRA_PACK_FOLDERS = []       # extra behaviour/resource pack folders, e.g. [r"C:\...\my_pack"]
LANGUAGES = ["en_GB", "en_US"] # which .lang files to use for text, in order of preference
SHOW_TRANSLATION_KEYS = True  # show the key next to translated text, e.g. "Hello (npc.greet)"
# ----------------------------------------------------------

DIM_IDS = {"minecraft:overworld": None, "minecraft:the_nether": 1, "minecraft:the_end": 2}

# Bedrock NPC action modes (as understood; shown alongside the number in the report)
ACTION_MODES = {0: "Button", 1: "On open", 2: "On close"}

# Data keys already shown in the report, or not useful for logic
KNOWN_KEYS = {
    "Actions", "Armor", "Attributes", "canPickupItems", "CustomName", "CustomNameVisible",
    "definitions", "hasSetCanPickupItems", "identifier", "InterativeText", "internalComponents",
    "LeasherID", "Mainhand", "Offhand", "OnGround", "OwnerNew", "Persistent", "Pos",
    "RawtextName", "Rotation", "Sitting", "Tags", "TargetID", "TradeExperience", "TradeTier",
    "UniqueID", "Variant", "Motion", "FallDistance", "Fire", "Invulnerable", "PortalCooldown",
    "IsGlobal", "IsAutonomous", "LinksTag", "LootDropped", "Air", "Chested", "Color", "Color2",
    "Dead", "IsAngry", "IsBaby", "IsEating", "IsGliding", "IsIllagerCaptain", "IsOrphaned",
    "IsOutOfControl", "IsPregnant", "IsRoaring", "IsScared", "IsStunned", "IsSwimming",
    "IsTamed", "IsTrusting", "Saddled", "Sheared", "ShowBottom", "Strength", "StrengthMax",
    "MarkVariant", "SkinID", "BodyRot", "boundX", "boundY", "boundZ", "hasBoundOrigin",
    "limitedLife", "NaturalSpawn", "Surface", "TargetCaptainID", "LastDimensionId",
    "Health", "HurtTime", "DeathTime", "AttackTime",
}

FUNCTION_RE = re.compile(r"(?:^|[\s/])function\s+([A-Za-z0-9_\-./:]+)", re.IGNORECASE)
DIALOGUE_RE = re.compile(r"(?:^|[\s/])dialogue\s+(?:open|change)\s+\S+(?:\s+\S+)?\s+([A-Za-z0-9_\-.:]+)", re.IGNORECASE)


# ================= NBT helpers =================
def _load_nbt(data):
    """Decode Bedrock little-endian NBT, coping with different amulet_nbt versions."""
    errors = []
    attempts = []
    for name in ("utf8_escape_decoder", "utf8_decoder"):
        dec = getattr(amulet_nbt, name, None)
        if dec is not None:
            attempts.append({"compressed": False, "little_endian": True, "string_decoder": dec})
    attempts.append({"compressed": False, "little_endian": True})
    for kwargs in attempts:
        try:
            return amulet_nbt.load(data, **kwargs)
        except Exception as e:
            errors.append(repr(e))
    raise ValueError("; ".join(errors))


def _py(tag):
    """Turn an NBT tag into plain Python (dict / list / str / number)."""
    for attr in ("compound", "tag"):  # NamedTag
        inner = getattr(tag, attr, None)
        if inner is not None and not hasattr(tag, "items"):
            return _py(inner)
    if hasattr(tag, "items") and callable(tag.items):
        return {str(k): _py(v) for k, v in tag.items()}
    if isinstance(tag, (str, int, float, bool)) or tag is None:
        return tag
    for attr in ("py_data", "py_str", "py_int", "py_float", "value"):
        try:
            v = getattr(tag, attr)
        except Exception:
            continue
        if callable(v) or v is None:
            continue
        if isinstance(v, (list, tuple)):
            return [_py(x) for x in v]
        if hasattr(v, "items") and callable(v.items):
            return {str(k): _py(x) for k, x in v.items()}
        if isinstance(v, (bytes, bytearray)):
            return v.hex()
        return v
    try:
        return [_py(x) for x in tag]
    except Exception:
        return str(tag)


# ================= NPC data helpers =================
LANG = {}  # filled in when the operation runs


def _tr(key):
    if key in LANG:
        return f"{LANG[key]} ({key})" if SHOW_TRANSLATION_KEYS else LANG[key]
    return f"[{key}]"


def _rawtext_parts(parts):
    out = []
    for p in parts if isinstance(parts, list) else []:
        if not isinstance(p, dict):
            continue
        if "text" in p:
            out.append(str(p["text"]))
        elif "translate" in p:
            out.append(_tr(p["translate"]))
        elif "score" in p:
            out.append(f"[score {p['score'].get('name','?')} {p['score'].get('objective','?')}]")
        elif "selector" in p:
            out.append(f"[{p['selector']}]")
        elif "rawtext" in p:
            out.append(_rawtext_parts(p["rawtext"]))
    return "".join(out)


def _rawtext(value):
    """Bedrock text may be plain, a translation key or rawtext JSON (possibly
    with extra text after it). Return readable text."""
    if isinstance(value, dict):
        return _rawtext_parts(value.get("rawtext", [])) if "rawtext" in value else str(value)
    if not isinstance(value, str):
        return "" if value is None else str(value)
    s = value.strip()
    if s.startswith("{"):
        try:
            obj, end = json.JSONDecoder().raw_decode(s)
            if isinstance(obj, dict) and "rawtext" in obj:
                return _rawtext_parts(obj["rawtext"]) + s[end:]
        except Exception:
            pass
    if s in LANG:  # a bare translation key
        return _tr(s)
    return value


def _compass(yaw):
    """Minecraft yaw: 0 = south, 90 = west, 180 = north, -90 = east."""
    try:
        yaw = float(yaw) % 360
    except Exception:
        return "unknown"
    names = ["south", "south-southwest", "southwest", "west-southwest",
             "west", "west-northwest", "northwest", "north-northwest",
             "north", "north-northeast", "northeast", "east-northeast",
             "east", "east-southeast", "southeast", "south-southeast"]
    return names[int((yaw + 11.25) // 22.5) % 16]


def _parse_actions(raw):
    """Parse the Actions JSON string into a list of dicts."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return [{"label": "Button", "mode": None, "name": "", "commands": [], "error": f"could not read: {raw!r}"}]
    actions = []
    for a in data if isinstance(data, list) else []:
        mode = a.get("mode")
        cmds = [d.get("cmd_line", "") for d in a.get("data", []) if isinstance(d, dict) and d.get("cmd_line")]
        if not cmds and a.get("text"):
            cmds = [ln for ln in str(a["text"]).splitlines() if ln.strip()]
        name = _rawtext(a.get("button_name", ""))
        if mode == 0 or (mode is None and name):
            label = "Button"
        else:
            label = ACTION_MODES.get(mode, f"Mode {mode}")
        if not cmds and not name:
            continue  # empty slot
        actions.append({"label": label, "mode": mode, "type": a.get("type"),
                        "name": name, "commands": cmds})
    return actions


def describe_npc(d):
    """Turn raw NPC data (plain dict) into a tidy description."""
    pos = d.get("Pos") or [0, 0, 0]
    try:
        exact = tuple(round(float(p), 2) for p in pos)
    except Exception:
        exact = (0, 0, 0)
    block = tuple(math.floor(p) for p in exact)
    rot = d.get("Rotation") or [0, 0]
    actions = _parse_actions(d.get("Actions"))
    all_cmds = [c for a in actions for c in a["commands"]]
    functions = []
    scenes = []
    for c in all_cmds:
        for f in FUNCTION_RE.findall(c):
            if f not in functions:
                functions.append(f)
        for s in DIALOGUE_RE.findall(c):
            if s not in scenes:
                scenes.append(s)
    other = {k: v for k, v in d.items() if k not in KNOWN_KEYS}
    return {
        "name": _rawtext(d.get("RawtextName")) or _rawtext(d.get("CustomName")) or "(no name)",
        "custom_name": _rawtext(d.get("CustomName")),
        "block": block,
        "exact": exact,
        "yaw": rot[0] if rot else 0,
        "facing": _compass(rot[0] if rot else 0),
        "skin": d.get("Variant", 0),
        "tags": d.get("Tags") or [],
        "dialogue": _rawtext(d.get("InterativeText")),
        "actions": actions,
        "functions": functions,
        "scenes": scenes,
        "other": other,
    }


# ================= Behaviour packs & functions =================
def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        txt = f.read()
    txt = re.sub(r"^\s*//.*$", "", txt, flags=re.MULTILINE)
    return json.loads(txt)


def find_packs(world_path):
    """Find behaviour and resource pack folders inside the world (plus extras)."""
    candidates = []
    if world_path:
        for sub in ("behavior_packs", "resource_packs"):
            root = os.path.join(world_path, sub)
            if os.path.isdir(root):
                for name in sorted(os.listdir(root)):
                    p = os.path.join(root, name)
                    if os.path.isdir(p):
                        candidates.append((p, "resource" if sub == "resource_packs" else "behaviour"))
    candidates += [(p, "extra") for p in EXTRA_PACK_FOLDERS if os.path.isdir(p)]
    packs = []
    for p, kind in candidates:
        name = os.path.basename(p)
        try:
            name = _read_json(os.path.join(p, "manifest.json")).get("header", {}).get("name", name)
        except Exception:
            pass
        packs.append({"path": p, "name": name, "kind": kind})
    return packs


def load_lang(packs):
    """Read .lang files from every pack's texts folder."""
    lang = {}
    for code in reversed(LANGUAGES):  # preferred language loaded last so it wins
        for pack in packs:
            path = os.path.join(pack["path"], "texts", f"{code}.lang")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\r\n")
                    if not line or line.lstrip().startswith("##") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    val = re.split(r"\t+#", val, 1)[0].rstrip()
                    val = val.replace("~LINEBREAK~", "\n").replace("\\n", "\n")
                    lang[key.strip()] = val
    # translate pack names like "pack.name"
    for pack in packs:
        texts = {}
        for code in reversed(LANGUAGES):
            path = os.path.join(pack["path"], "texts", f"{code}.lang")
            if os.path.isfile(path):
                with open(path, encoding="utf-8-sig", errors="replace") as f:
                    for line in f:
                        if line.startswith("pack.name="):
                            texts["pack.name"] = line.split("=", 1)[1].split("\t#")[0].strip()
        if pack["name"] in texts:
            pack["name"] = texts[pack["name"]]
    return lang


def load_scenes(packs):
    """Read dialogue scenes from every pack's dialogue folder."""
    scenes = {}
    for pack in packs:
        root = os.path.join(pack["path"], "dialogue")
        if not os.path.isdir(root):
            continue
        for dirpath, _d, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".json"):
                    continue
                try:
                    data = _read_json(os.path.join(dirpath, fn))
                except Exception:
                    continue
                for sc in data.get("minecraft:npc_dialogue", {}).get("scenes", []):
                    tag = sc.get("scene_tag")
                    if tag:
                        sc = dict(sc)
                        sc["_file"] = fn
                        sc["_pack"] = pack["name"]
                        scenes.setdefault(tag.lower(), sc)
    return scenes


def _cmds(lst):
    out = []
    for c in lst or []:
        out.append(c if isinstance(c, str) else json.dumps(c))
    return out


def scene_lines(tag, scenes, funcs, indent="      "):
    sc = scenes.get(str(tag).lower())
    if sc is None:
        return [f"{indent}scene {tag}  -- NOT FOUND in behaviour packs"]
    L = [f"{indent}scene {tag}  [{sc['_pack']} / {sc['_file']}]"]
    if sc.get("npc_name"):
        L.append(f"{indent}  Name: {_rawtext(sc['npc_name'])}")
    if sc.get("text"):
        L.append(f"{indent}  Text:")
        for ln in _rawtext(sc["text"]).splitlines() or [""]:
            L.append(f"{indent}    {ln}")
    groups = [("On open", sc.get("on_open_commands")), ("On close", sc.get("on_close_commands"))]
    for b in sc.get("buttons", []) or []:
        groups.append((f"Button \"{_rawtext(b.get('name', ''))}\"", b.get("commands")))
    called = []
    for label, cmds in groups:
        cmds = _cmds(cmds)
        if not cmds and label.startswith("On "):
            continue
        L.append(f"{indent}  {label}:")
        for c in cmds or ["(no commands)"]:
            L.append(f"{indent}    > {c}")
            for f in FUNCTION_RE.findall(c):
                if f not in called:
                    called.append(f)
    for f in called:
        L += expand_function(f, funcs, FUNCTION_DEPTH, indent=indent + "    ")
    return L


def load_functions(packs):
    """Return {function name (lowercase): {"name", "pack", "lines"}} and tick list."""
    funcs, ticks = {}, []
    for pack in packs:
        root = os.path.join(pack["path"], "functions")
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".mcfunction"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)[:-len(".mcfunction")].replace(os.sep, "/")
                try:
                    with open(full, encoding="utf-8-sig", errors="replace") as f:
                        lines = [ln.rstrip("\n") for ln in f]
                except Exception as e:
                    lines = [f"# could not read file: {e}"]
                funcs.setdefault(rel.lower(), {"name": rel, "pack": pack["name"], "lines": lines})
        try:
            with open(os.path.join(root, "tick.json"), encoding="utf-8-sig") as f:
                for v in json.load(f).get("values", []):
                    ticks.append(v)
        except Exception:
            pass
    return funcs, ticks


def expand_function(name, funcs, depth, seen=None, indent="      "):
    """Lines showing a function's contents, following nested function calls."""
    seen = set() if seen is None else seen
    key = name.lower().lstrip("/")
    out = []
    if key not in funcs:
        out.append(f"{indent}function {name}  -- NOT FOUND in behaviour packs")
        return out
    if key in seen:
        out.append(f"{indent}function {name}  -- (already shown above, loop)")
        return out
    seen.add(key)
    f = funcs[key]
    out.append(f"{indent}function {f['name']}  [{f['pack']}]")
    for ln in f["lines"]:
        if not ln.strip():
            continue
        out.append(f"{indent}  | {ln}")
        if depth > 1 and not ln.lstrip().startswith("#"):
            for sub in FUNCTION_RE.findall(ln):
                out += expand_function(sub, funcs, depth - 1, seen, indent + "      ")
    return out


# ================= Selection helpers =================
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


# ================= Report =================
def format_report(npcs, info, funcs, ticks, scenes):
    L = [
        f"NPC REPORT  (NPC Reader v{VERSION})",
        "=" * 60,
        f"World:      {info['world']}",
        f"Dimension:  {info['dimension']}",
        f"Generated:  {info['time']}",
        f"Scanned {info['chunks']} chunks ({info['scope']}) - found {len(npcs)} NPC(s)",
        f"Packs: {', '.join(info['packs']) if info['packs'] else 'none found in the world folder'}",
        f"Functions found: {len(funcs)}   Dialogue scenes found: {len(scenes)}   Text entries found: {info['lang']}",
        "",
        "Action modes: Button = player clicks it, On open = runs when the dialogue opens,",
        "On close = runs when it closes.",
        "",
    ]
    for i, n in enumerate(npcs, 1):
        L += ["-" * 60, f"NPC {i}: \"{n['name']}\"", "-" * 60]
        bx, by, bz = n["block"]
        ex, ey, ez = n["exact"]
        L.append(f"  At block ({bx}, {by}, {bz})   exact ({ex}, {ey}, {ez})   facing {n['facing']}")
        if n["custom_name"] and n["custom_name"] not in (n["name"], "NPC"):
            L.append(f"  Name tag: {n['custom_name']}")
        L.append(f"  Skin: {n['skin']}" + (f"   Tags: {', '.join(map(str, n['tags']))}" if n["tags"] else ""))
        L.append("  Dialogue:")
        for ln in (n["dialogue"] or "(none)").splitlines() or ["(none)"]:
            L.append(f"    {ln}")
        if not n["actions"]:
            L.append("  Buttons / commands: none")
        for a in n["actions"]:
            title = f"  {a['label']}"
            if a["label"] == "Button":
                title += f" \"{a['name']}\""
            L.append(title + ":")
            for c in a["commands"] or ["(no commands)"]:
                L.append(f"    > {c}")
        if n["scenes"]:
            L.append("  Dialogue scenes opened:")
            for sc in n["scenes"]:
                L += scene_lines(sc, scenes, funcs)
        if n["functions"]:
            L.append("  Functions called:")
            for f in n["functions"]:
                L += expand_function(f, funcs, FUNCTION_DEPTH)
        if n["other"]:
            L.append("  Other data: " + ", ".join(f"{k}={v}" for k, v in n["other"].items()))
        L.append("")
    if not npcs:
        L.append("No NPCs found.")
        L.append("")
    if ticks:
        L += ["=" * 60, "FUNCTIONS THAT RUN EVERY TICK (tick.json)", "=" * 60]
        L += [f"  {t}" for t in ticks]
        L.append("")
    if scenes:
        L += ["=" * 60, "ALL DIALOGUE SCENES", "=" * 60]
        for key in sorted(scenes):
            L += scene_lines(scenes[key]["scene_tag"], scenes, funcs, indent="")
            L.append("")
    if LIST_ALL_FUNCTIONS and funcs:
        L += ["=" * 60, "ALL FUNCTIONS IN THE BEHAVIOUR PACKS", "=" * 60]
        for key in sorted(funcs):
            f = funcs[key]
            L.append(f"function {f['name']}  [{f['pack']}]")
            L += [f"  | {ln}" for ln in f["lines"] if ln.strip()]
            L.append("")
    return "\n".join(L)


# ================= The operation =================
def read_npcs(world: BaseLevel, dimension: Dimension, selection: SelectionGroup, options: dict):
    wrapper = world.level_wrapper
    db = getattr(wrapper, "level_db", None) or getattr(wrapper, "_level_db", None)
    if db is None:
        print("[NPC Reader] Couldn't open the world database. NPC Reader works with Bedrock worlds only.")
        return

    boxes = _boxes(selection)
    if boxes:
        chunk_list = sorted(_chunk_coords(boxes))
        scope = "selection"
    else:
        chunk_list = sorted(world.all_chunk_coords(dimension))
        scope = "whole dimension"

    world_path = getattr(wrapper, "path", None)
    packs = find_packs(world_path)
    LANG.clear()
    LANG.update(load_lang(packs))
    funcs, ticks = load_functions([p for p in packs if p["kind"] != "resource"])
    scenes = load_scenes([p for p in packs if p["kind"] != "resource"])

    dim_id = DIM_IDS.get(str(dimension))
    total = len(chunk_list)
    print(f"[NPC Reader v{VERSION}] Scanning {total} chunks ({scope})...")

    npcs, failed = [], 0
    for start in range(0, total, BATCH_SIZE):
        for cx, cz in chunk_list[start:start + BATCH_SIZE]:
            key = b"digp" + struct.pack("<ii", cx, cz)
            if dim_id is not None:
                key += struct.pack("<i", dim_id)
            try:
                ids = db.get(key)
            except Exception:
                continue
            if not ids:
                continue
            for i in range(0, len(ids), 8):
                try:
                    raw = db.get(b"actorprefix" + ids[i:i + 8])
                    data = _py(_load_nbt(raw))
                except Exception:
                    failed += 1
                    continue
                if not isinstance(data, dict) or "npc" not in str(data.get("identifier", "")):
                    continue
                n = describe_npc(data)
                if boxes and not _inside(boxes, *n["block"]):
                    continue
                npcs.append(n)
        yield min(start + BATCH_SIZE, total) / total if total else 1.0

    npcs.sort(key=lambda n: (n["block"][0], n["block"][2], n["block"][1]))

    world_name = getattr(wrapper, "level_name", None) or "world"
    info = {
        "world": world_name,
        "dimension": str(dimension),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunks": total,
        "scope": scope,
        "packs": [f"{p['name']} ({p['kind']})" for p in packs],
        "lang": len(LANG),
    }

    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in str(world_name)).strip()
    folder = OUTPUT_FOLDER or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "npc_reports")
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"npcs_{safe}_{time.strftime('%Y-%m-%d_%H-%M-%S')}")

    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(format_report(npcs, info, funcs, ticks, scenes))
    if WRITE_JSON:
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"info": info, "npcs": npcs, "tick_functions": ticks, "scenes": scenes,
                       "functions": {k: v for k, v in funcs.items()}},
                      f, indent=2, default=str)

    print(f"[NPC Reader] Found {len(npcs)} NPC(s). Packs: {len(packs)}, functions: {len(funcs)}, scenes: {len(scenes)}, text entries: {len(LANG)}.")
    if failed:
        print(f"[NPC Reader] {failed} entities couldn't be decoded and were skipped.")
    print(f"[NPC Reader] Report saved to: {base}.txt")


export = {
    "name": "NPC Reader",
    "operation": read_npcs,
}
