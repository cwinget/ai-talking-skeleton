# Skeleton electronics box v7

ElectroCookie (half size) and ReSpeaker Lite side by side, radar bay at one
end, connectors on that end wall. The lid is the front panel (faces visitors).

**Outside: 98.6 x 127 x 29.5 mm** (with lid), plus 11 mm of tie-down ears at the far end.

## v7 changes
- Lid: the two top-right grille cells (next to the side wall, level with the camera)
  are merged into one opening, removing the web that pressed the ReSpeaker's mute
  button (`GRILLE_MERGE`).
- AUX hole raised 1 mm (center 5.7 mm below the top edge of the base).
- Two tie-down ears on the far-end wall (opposite the connectors), flush with the
  bottom of the box, each with a 5 mm hole for wire, string or zip ties
  (`EAR_*` parameters). They add 11 mm to the box's length.

## v6 changes
- ReSpeaker moved 26.25 mm toward the connector wall (its jack-end edge 0.5 mm from the
  wall, the jack's nose sitting in the new wall hole). That leaves **37.6 mm** free past
  the XIAO's USB-C for the pigtail (was 11.4). Grille moved with it. Box size unchanged.
- JAW connector removed; **AUX** headphone hole added (7.0 mm, centered 11.5 mm from the
  ReSpeaker-side outer wall and 6.7 mm below the top edge of the base).
- Remaining connectors re-spaced (PWR 15, SPK 32, LED 49 mm from the inner left wall)
  so their nuts clear the ReSpeaker.
- **3 lid screws** now: the corner post at the connector wall on the ReSpeaker side was
  under the ReSpeaker. The locating lip is also cut back along that stretch.
- Radar slot moved 4 mm toward the ElectroCookie side (it overlapped the ReSpeaker), and
  the lip cut-back at its open end is 5 mm (was 4).

## v5 changes
- Radar slot 1 mm bigger in both directions (`RADAR_FIT` 0.65/side), thickness fit
  0.25/side, grooves 1.3 mm deep (~0.65 mm of each edge gripped), and the lips are cut
  back for the first 4 mm at the open end so the pin header passes (`RADAR_PIN_RELIEF`).
- M2.5 holes enlarged for printing: post pilots 2.4 mm (was 2.2), lid holes 3.0 mm (was 2.9).
  Affects the lid screws and the ElectroCookie's two screw posts.

## v4 changes
- ElectroCookie posts back to 5 mm (box 29.5 mm tall).
- Radar is now **slide-in**: two grooved rails + an end stop on the lid's underside
  (see `radar_holder.png`). The board slides in parallel to the lid from the
  ElectroCookie side, antenna toward the lid, **pin edge last** (at the open end).


## v3 changes
- Shorter: the camera lens now pokes through the lid, so the lid only clears the ESP32 (0.5 mm).
- ReSpeaker flat side up (bottom-ported mics right under the grille), 2 mm under the lid
  for M2 screw heads; XIAO side faces the floor. Moved 1.25 mm away from its wall to
  clear the lid's locating lip.
- Connectors lowered 2 mm and the radar pocket moved 1 mm from the wall so they don't collide.

## v2 changes
- 2 mm more room between the ElectroCookie and its side wall (board positions unchanged relative to each other).
- ReSpeaker mounted **face-down** (`RS_FLIPPED = true`): holes mirrored left/right.
- ElectroCookie corner M2 holes are now **locating pins** (1.9 mm, chamfered); screws only in the two center holes.

## Files
- `skeleton_box_test.stl`: **print this first.** Just the floor with short posts and
  raised board outlines. Screw both boards on to check every hole before the full print.
- `skeleton_box_base.stl`: print upright (floor down), no supports.
- `skeleton_box_lid.stl`: already flipped; print outside face down, no supports.
- `skeleton_box.scad`: the source. Every dimension is a named value at the top.
  Change `PART = "base" | "lid" | "test" | "assembly"` to render each piece.

## Screws
| What | Screw | Post pilot |
|---|---|---|
| ElectroCookie, center M3 holes | M2.5 | 2.4 mm |
| ElectroCookie, corner holes | none: locating pins | — |
| ReSpeaker (2 diagonal holes) | M2 x ~6 mm | 1.7 mm |
| Lid (3 corners) | M2.5 x ~10 mm | 2.4 mm (lid holes 3.0) |

If the ESP32 covers a center hole, the pins still locate the board; one screw is enough to hold it.

## End wall (left to right, from outside)
PWR (USB-C jack, double-D hole 11.1 / 10.1 mm), SPK, LED (GX12, 12.2 mm), AUX (7 mm,
headphone). Labels are debossed on the wall.

## ASSUMED values: please measure and tell me
| Parameter | Assumed | What to measure |
|---|---|---|
| `RADAR_W`, `RADAR_L`, `RADAR_T` | 22 x 16 x 1.2 mm | radar board outline + thickness; pins must be on a short (16 mm) edge |
| ReSpeaker underside | 19.9 mm posts | tallest part on the XIAO side (must be < ~18 mm) |
| `STACK_CLEAR` | 0.5 mm | is 20 mm the true top of the ESP32 board, excluding the camera? |
| GX12 hole | 12.2 mm | check against your connectors' thread |

Not included yet: a window for the body board's status LED (need its position),
and a side slot for reaching the ReSpeaker's USB-C without opening the lid.
