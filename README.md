# Amulet Plugins by Wizard Keen

Operations for [Amulet Map Editor](https://www.amuletmc.com/), the Minecraft world editor. Together they help you work out how a map's logic fits together without flying around clicking on things.

- **[Command Block Reader](#command-block-reader)**: every command block and chain, in run order.
- **[NPC Reader](#npc-reader)**: every NPC's dialogue, buttons and commands, plus the functions and dialogue scenes they trigger. Bedrock only.

Both plugins only read the world. They never change anything.

## Command Block Reader

Finds every command block in your selection, or the whole world if nothing is selected, reads it and writes a report. Command block chains are listed in the order they run, so you can see how a map's logic works without flying around clicking on blocks.

For each command block, the report gives:

- position (x, y, z)
- type: impulse, chain or repeating
- facing direction
- conditional or unconditional
- always active or needs redstone
- tick delay
- custom name
- the command itself
- its last output (handy for spotting broken commands)

Chains are followed along each block's facing arrow, and closed loops are flagged. The plugin only reads the world. It never changes anything.

### Example report

```
CHAIN 3  (3 blocks)
------------------------------------------------------------
  1. IMPULSE   at (120, 64, -40)  facing east  |  needs redstone, unconditional
     Name:    start game
     Command: /tag @p add playing
     Last output: commands.tag.add.success.single
  2. CHAIN     at (121, 64, -40)  facing east  |  always active, conditional
     Command: /tp @p 200 70 -40
  3. CHAIN     at (122, 64, -40)  facing up  |  always active, conditional
     Command: /title @p title Welcome!
```

A `.json` copy of the report is saved alongside the `.txt`, in case you want to process the data further.

### Install

1. Download `command_block_reader.py`.
2. Put it in Amulet's operations folder. On Windows that's
   `C:\Users\<you>\AppData\Local\AmuletTeam\AmuletMapEditor\plugins\operations\`
3. Open Amulet. If it's already open, press the refresh button in the Operations tab.

### Use

1. **Back up your world first.** The plugin only reads, but it's good practice.
2. Open the world in Amulet's 3D editor. Drag a selection box around the area you want to scan, or select nothing to scan the whole dimension you're viewing (Overworld, Nether or End).
3. Go to the **Operations** tab, choose **Command Block Reader** and press **Run Operation**.
4. The console tells you how many command blocks it found and where it saved the report. By default that's
   `...\AmuletMapEditor\plugins\command_block_reports\`

Make the selection generous. A chain that runs out of the selection is cut off at the edge.

### Settings

At the top of the file:

| Setting | Default | What it does |
|---|---|---|
| `BATCH_SIZE` | `10` | Chunks loaded before memory is freed. Lower it on slower machines. |
| `SCAN_WHOLE_DIMENSION` | `False` | `True` scans every chunk and ignores the selection. |
| `OUTPUT_FOLDER` | `""` | Where reports are saved. Leave blank for the default folder. |
| `WRITE_JSON` | `True` | Also write a `.json` copy. |

### Tested with

- Amulet 0.10.66 on Windows
- A Bedrock Edition world (1.26.60), with 124 command blocks across 3,776 chunks

It should work with Java Edition worlds too, but this hasn't been tested yet. Reports from Java users are welcome.

## NPC Reader

Finds every NPC in your selection, or the whole dimension if nothing is selected, and writes a report of what each one says and does. Bedrock Edition only.

For each NPC, the report gives:

- position (block and exact coordinates) and which way it faces
- name, skin and tags
- dialogue text
- each button and the commands it runs
- commands that run when the dialogue opens or closes

It also looks inside the world's behaviour and resource packs:

- **Functions:** any function an NPC calls is shown with its contents underneath, following nested calls (loops and missing functions are flagged).
- **Dialogue scenes:** if an NPC opens a `/dialogue` scene, the scene's text, buttons and commands are shown too.
- **Translations:** text stored as translation keys (as Marketplace maps do) is looked up in the pack's `.lang` files, so you see the actual words.
- **Appendices:** functions that run every tick, every dialogue scene, and every function in the pack.

### Example report

```
NPC 3: "Gatekeeper (gate.npc)"
------------------------------------------------------------
  At block (-40, 64, 12)   exact (-39.5, 64.0, 12.5)   facing east
  Skin: 7
  Dialogue:
    Only those who have found all three keys may pass. (gate.dialogue)
  On open:
    > /tag @p add met_gatekeeper
  Button "Open the gate (gate.button)":
    > /function gate/check
  Functions called:
      function gate/check  [My Adventure Map]
        | execute as @p[tag=key1,tag=key2,tag=key3] run function gate/open
            function gate/open  [My Adventure Map]
              | fill -38 64 10 -38 66 14 air
              | playsound random.door_open @p
```

### Install and use

Same as the Command Block Reader: put `npc_reader.py` in Amulet's `plugins\operations` folder, restart Amulet, open the world, then run **NPC Reader** from the Operations tab. Reports are saved to
`...\AmuletMapEditor\plugins\npc_reports\`

### How it works

Amulet's normal entity loading doesn't see entities in current Bedrock worlds, so the NPC Reader reads the world's database directly. It still only reads.

### Settings

| Setting | Default | What it does |
|---|---|---|
| `OUTPUT_FOLDER` | `""` | Where reports are saved. Leave blank for the default folder. |
| `WRITE_JSON` | `True` | Also write a `.json` copy. |
| `FUNCTION_DEPTH` | `3` | How deep to follow functions that call other functions. |
| `LIST_ALL_FUNCTIONS` | `True` | Add an appendix with every function in the packs. |
| `LANGUAGES` | `["en_GB", "en_US"]` | Which `.lang` files to use for text, in order of preference. |
| `SHOW_TRANSLATION_KEYS` | `True` | Show each translation key next to its text. |
| `EXTRA_PACK_FOLDERS` | `[]` | Extra pack folders to search, if a world's packs aren't inside its folder. |

### Tested with

- Amulet 0.10.66 on Windows
- A Bedrock Edition world (1.26.60) with 66 NPCs, 82 functions and 13 dialogue scenes

## Licence

MIT. Use it, change it and share it. See [LICENSE](LICENSE).
