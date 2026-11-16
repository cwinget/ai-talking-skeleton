# Servo horn for 2 mm wire

> **Not used in the final build.** The original skeleton used the servo's stock plastic arm
> with a hole drilled through it for the 2 mm aluminium wire (see `docs/HARDWARE.md` → Jaw
> servo). This printed horn is an untested alternative.

- `servo_horn.stl`: print as-is (arm flat on the bed). 100% infill or 4+ walls; PETG is
  tougher than PLA here.
- `servo_horn_bore_test.stl`: print first. Press each hub onto the servo shaft by hand.
  Pick the **smallest bore you can press on fully** without cracking the hub; it should
  not spin by hand. Set `BORE_D` in `servo_horn.scad` to that size and re-export
  (default 4.3).
- Wire holes are drawn at 2.4 mm and print near 2.2 mm. If the wire binds, drill them
  out with a 2.2-2.3 mm (3/32") bit.
- Holes at 8, 11, 14, 17 mm from the shaft. Farther out = more wire travel per degree
  (more jaw movement); closer in = less travel, more force.
- Screw: M2.5 through the top into the shaft, head sits in a 0.6 mm recess. If your
  servo's shaft screw is actually M2, it still fits (2.9 mm hole).
