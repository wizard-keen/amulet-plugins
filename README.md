# Amulet Plugins by Wizard Keen

Operations for [Amulet Map Editor](https://www.amuletmc.com/), the Minecraft world editor.

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

## Licence

MIT. Use it, change it and share it. See [LICENSE](LICENSE).
