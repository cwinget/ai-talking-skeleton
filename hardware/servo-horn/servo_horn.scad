// =====================================================================
//  Servo horn for a 2 mm pushrod wire (MG90S-style servo)
//  PART = "horn" | "bore_test"
//  The splined shaft is too fine to print, so the hub is a round press-fit:
//  slightly smaller than the shaft so its teeth cut into the plastic.
//  Print bore_test first and use the bore that presses on firmly.
// =====================================================================
PART = "horn";
$fn = 64;

SHAFT_D   = 4.5;     // measured spline diameter
BORE_D    = 4.3;     // press-fit bore (pick from bore_test)
HUB_OD    = 9.0;
HUB_H     = 5.0;     // depth of the bore (how far the hub goes over the shaft)
TOP_T     = 1.6;     // material above the shaft, under the screw head
SCREW_CLEAR = 2.9;   // M2.5 screw through the top
HEAD_D    = 5.0;     // counterbore so the screw head sits flush-ish
HEAD_RECESS = 0.6;

ARM_T     = 2.6;     // arm thickness
ARM_W_HUB = 7.0;     // arm width at the hub
ARM_W_TIP = 5.0;     // arm width at the tip
WIRE_HOLE = 2.4;     // for 2 mm wire (prints ~2.2)
HOLE_RADII = [8, 11, 14, 17];   // wire holes, mm from the shaft center
ARM_LEN   = HOLE_RADII[len(HOLE_RADII) - 1] + 3.5;

module arm2d() {
  hull() {
    circle(d = ARM_W_HUB);
    translate([ARM_LEN - ARM_W_TIP / 2, 0]) circle(d = ARM_W_TIP);
  }
}

module horn() {
  total_h = HUB_H + TOP_T;
  difference() {
    union() {
      cylinder(h = total_h, d = HUB_OD);
      // the arm sits at the top of the hub (screw side), like a stock horn
      translate([0, 0, total_h - ARM_T]) linear_extrude(ARM_T) arm2d();
    }
    // press-fit bore from the bottom, with a small lead-in chamfer
    translate([0, 0, -0.01]) cylinder(h = HUB_H + 0.01, d = BORE_D);
    translate([0, 0, -0.01]) cylinder(h = 0.6, d1 = BORE_D + 0.8, d2 = BORE_D);
    // screw hole + head recess
    cylinder(h = total_h + 1, d = SCREW_CLEAR);
    translate([0, 0, total_h - HEAD_RECESS]) cylinder(h = 1, d = HEAD_D);
    // wire holes
    for (r = HOLE_RADII) translate([r, 0, -1]) cylinder(h = total_h + 2, d = WIRE_HOLE);
  }
}

// Four short hubs with different bores, labeled by size.
module bore_test() {
  bores = [4.1, 4.2, 4.3, 4.4];
  for (i = [0 : len(bores) - 1]) translate([i * 12, 0, 0]) {
    difference() {
      cylinder(h = HUB_H, d = HUB_OD);
      translate([0, 0, -0.01]) cylinder(h = HUB_H + 0.02, d = bores[i]);
      translate([0, 0, -0.01]) cylinder(h = 0.6, d1 = bores[i] + 0.8, d2 = bores[i]);
    }
    // label tab
    difference() {
      translate([-4.5, -HUB_OD / 2 - 6, 0]) cube([9, 6.5, 1.2]);
      translate([0, -HUB_OD / 2 - 4.6, 0.6]) linear_extrude(1)
        text(str(bores[i]), size = 3, halign = "center", font = "Liberation Sans:style=Bold");
    }
    // bridge to the next hub
    if (i < len(bores) - 1) translate([HUB_OD / 2 - 0.5, -1.5, 0]) cube([12 - HUB_OD + 1, 3, 1.2]);
  }
}

// "horn" is exported upside down: arm flat on the bed, bore facing up.
if (PART == "horn") translate([0, 0, HUB_H + TOP_T]) rotate([180, 0, 0]) horn();
else bore_test();
