// =====================================================================
//  Talking Skeleton electronics box  (v7)
//  ElectroCookie (half size) + ReSpeaker Lite side by side, radar bay at
//  one end, connectors on the radar-bay end wall. Lid = front panel.
//
//  Render one part at a time:  PART = "base" | "lid" | "test" | "assembly"
//  All dimensions in mm.  Values marked ASSUMED need checking.
// =====================================================================
PART = "assembly";

$fn = 48;
eps = 0.01;

// ------------------------------------------------------------- shell
WALL      = 2.5;    // side wall thickness
FLOOR     = 2.0;    // floor thickness
LID_T     = 2.0;    // lid plate thickness
CLEAR     = 0.75;   // gap between boards and walls
BAY       = 24;     // radar/connector bay length (at y = 0 end)
FAR_CLEAR = 8.5;    // room at the far end for lid screw posts

// ------------------------------------------------------------- ElectroCookie (measured)
CK_W = 52.0;   CK_L = 88.8;   CK_T = 1.6;
CK_POST_H   = 5;      // height of posts under the board
CK_STACK    = 20;     // board bottom -> top of ESP32 (measured, excl. camera)
// holes from the cookie's bottom-left corner (from the ElectroCookie case file)
CK_M3_HOLES = [[26.0, 7.55], [26.0, CK_L - 7.55]];          // use M2.5 screws
CK_M2_HOLES = [[8.1, 4.95], [43.9, 4.95], [8.1, CK_L - 4.95], [43.9, CK_L - 4.95]];
// camera (measured to the lens' near edges, from the cookie's TOP and LEFT edges)
CAM_D        = 7.8;
CAM_FROM_TOP = 26.5;
CAM_FROM_LEFT= 24.2;
CAM_ABOVE_STACK = 4.5;    // ASSUMED: lens top above the 20 mm stack
CAM_HOLE_D   = 9.0;       // hole in the lid (the lens pokes through)
CAM_HOLE_FLARE = 9.0;     // = CAM_HOLE_D: no viewing cone needed when the lens sticks out

// ------------------------------------------------------------- ReSpeaker Lite (measured)
RS_W = 34.1;   RS_L = 82.2;   RS_T = 1.6;
RS_POKE_TOP = 1.7;   RS_POKE_BOTTOM = 2.0;   // connectors sticking out the ends
// holes from the board's bottom-left corner; spacing taken from the ReSpeaker case (29.1 x 57.6)
RS_FLIPPED = true;        // board mounted face-down (holes mirror left <-> right)
RS_HOLE_B0 = [RS_W - 2.3, RS_L - 2.3];                     // face-up: top-right hole
RS_HOLE_A0 = [RS_HOLE_B0[0] - 29.1, RS_HOLE_B0[1] - 57.6]; // face-up: bottom-left hole
function rs_hole(h) = RS_FLIPPED ? [RS_W - h[0], h[1]] : h;
RS_HOLE_A = rs_hole(RS_HOLE_A0);
RS_HOLE_B = rs_hole(RS_HOLE_B0);
RS_GAP_TO_LID = 2.0;      // flat side faces the lid; room for M2 screw heads
BOARD_GAP = 2.75;         // gap between the two boards
RS_SIDE_CLEAR = 2.0;      // ReSpeaker to its side wall (clears the lid's locating lip)
CK_SIDE_EXTRA = 2;        // extra room between the ElectroCookie and its side wall

// ------------------------------------------------------------- grille
GRILLE_CELL = 6;  GRILLE_WEB = 1.4;
// pairs of grille cells [i, j] merged into one opening (removes the web between them)
GRILLE_MERGE = [ [[3, 12], [4, 12]] ];   // top-right: web was pressing the ReSpeaker's mute button

// ------------------------------------------------------------- tie-down loops
EAR_FROM_SIDE = 15;       // ear centers, measured in from each side wall
EAR_W = 12;               // ear width
EAR_REACH = 11;           // how far the ears stick out past the far-end wall
EAR_T = 4;                // ear thickness (flush with the bottom of the box)
EAR_HOLE = 5;             // fits wire, string or zip ties

// ------------------------------------------------------------- radar (LD2410C)
RADAR_W = 22;  RADAR_L = 16;  RADAR_T = 1.2;   // ASSUMED size
RADAR_AIR = 3;            // air gap between antenna and lid
RADAR_GROOVE = 1.3;       // groove depth into each rail
RADAR_FIT = 0.65;         // in-plane clearance per side (slot is 1.3 mm bigger than the board)
RADAR_FIT_T = 0.25;       // thickness clearance per side in the grooves
RADAR_PIN_RELIEF = 5;     // lips cut back this far at the open end so the pin header passes
// The board slides in along X from the -X end (ElectroCookie side), pin edge last.

// ------------------------------------------------------------- connectors (end wall)
CONN_Z = 10;              // height of connector centers above the floor
USBC_D = 11.1;  USBC_FLAT = 10.1;   // M11 jack, double-D panel hole
GX12_D = 12.2;
AUX_D = 7.0;              // headphone jack hole (generous so the plug lines up)
AUX_FROM_SIDE = 11.5;     // hole center from the ReSpeaker-side outer wall (measured)
AUX_FROM_TOP = 5.7;       // hole center below the top edge of the base (measured 6.7, moved up 1 mm)
// [label, x position (interior), type]
CONNECTORS = [["PWR", 15, "usbc"], ["SPK", 32, "gx12"], ["LED", 49, "gx12"]];

// ------------------------------------------------------------- screws
M25_PILOT = 2.4;   M2_PILOT = 1.7;   LID_SCREW_CLEAR = 3.0;   // M2.5 (printed holes shrink ~0.2)
PIN_D = 1.9;              // locating pins for the ElectroCookie's 2.2 mm corner holes
PIN_PROUD = 1.0;          // how far the pins stick up above the board

// ------------------------------------------------------------- derived
IW = CK_SIDE_EXTRA + CLEAR + CK_W + BOARD_GAP + RS_W + RS_SIDE_CLEAR;   // interior width
IL = BAY + CLEAR + CK_L + FAR_CLEAR;                     // interior length
STACK_CLEAR = 0.5;                                       // ESP32 top to lid
IH = CK_POST_H + CK_STACK + STACK_CLEAR;                 // interior height (camera pokes through the lid)
OW = IW + 2*WALL;  OL = IL + 2*WALL;

CK_X = CK_SIDE_EXTRA + CLEAR;  CK_Y = BAY + CLEAR;       // cookie bottom-left
RS_X = CK_X + CK_W + BOARD_GAP;
RS_WALL_GAP = 0.5;                                       // ReSpeaker jack-end edge to the connector wall
RS_Y = RS_WALL_GAP;                                      // ReSpeaker bottom-left (jack nose sits in the wall hole)
RS_POST_H = IH - RS_GAP_TO_LID - RS_T;
CAM_C = [CK_X + CAM_FROM_LEFT + CAM_D/2, CK_Y + CK_L - CAM_FROM_TOP - CAM_D/2];
RADAR_C = [IW/2 - 4, BAY/2 + 2];
BOSS_R = 3.5;  BOSS_IN = 3.6;                            // lid screw posts
// three lid screws: the fourth corner (connector wall, ReSpeaker side) is under the ReSpeaker
BOSSES = [[BOSS_IN, BOSS_IN], [BOSS_IN, IL-BOSS_IN], [IW-BOSS_IN, IL-BOSS_IN]];

echo(str("Outside: ", OW, " x ", OL, " x ", FLOOR + IH + LID_T, " mm (with lid)"));
echo(str("ReSpeaker post height: ", RS_POST_H));

// ===================================================================== base
module label(t, x, z) {
  translate([x, -WALL - eps, z]) rotate([90, 0, 180]) linear_extrude(0.6) mirror([1, 0, 0])
    text(t, size = 4, halign = "center", font = "Liberation Sans:style=Bold");
}

module post(h, od, pilot) {
  difference() {
    union() {
      cylinder(h = h, d = od);
      cylinder(h = min(4, h), d1 = od + 3, d2 = od);   // flared foot
    }
    translate([0, 0, -1 - eps]) cylinder(h = h + 2, d = pilot);
  }
}

module pin_post(h, od, pin_d, pin_h) {
  cylinder(h = h, d = od);
  cylinder(h = min(4, h), d1 = od + 3, d2 = od);
  translate([0, 0, h - eps]) {
    cylinder(h = pin_h - 0.5, d = pin_d);
    translate([0, 0, pin_h - 0.5 - eps]) cylinder(h = 0.5, d1 = pin_d, d2 = pin_d - 0.6);  // chamfered tip
  }
}

module conn_hole(kind) {
  if (kind == "usbc")
    intersection() {
      rotate([90, 0, 0]) cylinder(h = 20, d = USBC_D, center = true);
      cube([20, 20, USBC_FLAT], center = true);
    }
  else
    rotate([90, 0, 0]) cylinder(h = 20, d = GX12_D, center = true);
}

// Tie-down ears on the far-end wall (opposite the connectors), flush with the
// bottom of the box so they print without supports. A sloped brace ties each
// ear into the wall.
module ears() {
  xs = [EAR_FROM_SIDE, IW - EAR_FROM_SIDE];
  for (x = xs) translate([x, IL + WALL, -FLOOR]) difference() {
    hull() {
      translate([-EAR_W/2, -0.1, 0]) cube([EAR_W, 0.1, EAR_T + 6]);          // tall at the wall
      translate([-EAR_W/2, -0.1, 0]) cube([EAR_W, EAR_REACH - EAR_W/2, EAR_T]);
      translate([0, EAR_REACH - EAR_W/2, 0]) cylinder(h = EAR_T, d = EAR_W);
    }
    translate([0, EAR_REACH - EAR_W/2, -1]) cylinder(h = EAR_T + 10, d = EAR_HOLE);
  }
}

module base() {
  difference() {
    union() {
      // shell
      difference() {
        translate([-WALL, -WALL, -FLOOR]) cube([OW, OL, FLOOR + IH]);
        cube([IW, IL, IH + 1]);
      }
      // ElectroCookie posts
      for (h = CK_M3_HOLES) translate([CK_X + h[0], CK_Y + h[1], 0]) post(CK_POST_H, 6.0, M25_PILOT);
      for (h = CK_M2_HOLES) translate([CK_X + h[0], CK_Y + h[1], 0]) pin_post(CK_POST_H, 4.6, PIN_D, CK_T + PIN_PROUD);
      // ReSpeaker posts (tall)
      for (h = [RS_HOLE_A, RS_HOLE_B]) translate([RS_X + h[0], RS_Y + h[1], 0]) post(RS_POST_H, 6.0, M2_PILOT);
      // lid screw posts in the corners
      for (b = BOSSES) translate([b[0], b[1], 0]) cylinder(h = IH, r = BOSS_R);
      ears();
    }
    // lid screw pilots
    for (b = BOSSES) translate([b[0], b[1], IH - 10]) cylinder(h = 11, d = M25_PILOT);
    // connector holes in the y = 0 end wall + labels
    for (c = CONNECTORS) {
      translate([c[1], -WALL/2, CONN_Z]) conn_hole(c[2]);
      label(c[0], c[1], CONN_Z + GX12_D/2 + 2.5);
    }
    // headphone jack (ReSpeaker's 3.5 mm output)
    aux_x = IW + WALL - AUX_FROM_SIDE;
    aux_z = IH - AUX_FROM_TOP;
    translate([aux_x, -WALL/2, aux_z]) rotate([90, 0, 0]) cylinder(h = 20, d = AUX_D, center = true);
    label("AUX", aux_x, aux_z - AUX_D/2 - 5.5);
  }
}

// ===================================================================== lid
module hexcell(i, j, cell, web, h) {
  dx = cell + web;  dy = (cell + web) * sqrt(3) / 2;
  translate([i * dx + (j % 2) * dx / 2, j * dy, 0]) cylinder(h = h, d = cell / cos(30), $fn = 6);
}

module hexgrid(w, l, cell = GRILLE_CELL, web = GRILLE_WEB, h = 10, merge = []) {
  dx = cell + web;  dy = (cell + web) * sqrt(3) / 2;
  intersection() {
    cube([w, l, h]);
    union() {
      for (j = [-1 : ceil(l / dy) + 1], i = [-1 : ceil(w / dx) + 1]) hexcell(i, j, cell, web, h);
      for (m = merge) hull() for (c = m) hexcell(c[0], c[1], cell, web, h);
    }
  }
}

module radar_holder() {
  rw = 1.2;                                     // rail wall behind the groove
  lip = 1.2;                                    // material below the board
  slot_t = RADAR_T + 2*RADAR_FIT_T;             // groove height
  depth = RADAR_AIR + slot_t + lip;
  gl = RADAR_W + 2*RADAR_FIT;                   // slot length (slide direction, X)
  gw = RADAR_L + 2*RADAR_FIT;                   // slot width at the groove bottoms (Y)
  z_board_top = IH - RADAR_AIR;                 // antenna face
  translate([RADAR_C[0] - gl/2, RADAR_C[1], 0]) {
    for (side = [-1, 1]) {
      y0 = side > 0 ? gw/2 - RADAR_GROOVE : -gw/2 - rw;
      difference() {
        translate([0, y0, IH - depth]) cube([gl + rw, RADAR_GROOVE + rw, depth + 0.2]);
        // groove the board edge slides in
        translate([-1, side > 0 ? gw/2 - RADAR_GROOVE - 1 : -gw/2 - eps, z_board_top - slot_t])
          cube([gl + 1, RADAR_GROOVE + 1 + eps, slot_t]);
        // relief: lips below the groove cut back at the open end for the pin header
        translate([-1, side > 0 ? gw/2 - RADAR_GROOVE - 1 : -gw/2 - eps, IH - depth - 1])
          cube([RADAR_PIN_RELIEF + 1, RADAR_GROOVE + 1 + eps, lip + 1 + eps]);
      }
    }
    // end stop at +X (closes the slot)
    translate([gl, -gw/2 - rw, IH - depth]) cube([rw, gw + 2*rw, depth + 0.2]);
  }
}

module lid() {
  // modeled in place (z = IH is the lid's inner face); print it upside down
  lip = 2.0;  lip_t = 1.2;  lip_gap = 0.3;  corner_skip = 2 * BOSS_R + 3;
  difference() {
    union() {
      translate([-WALL, -WALL, IH]) cube([OW, OL, LID_T]);
      // locating lip inside the walls (skips the corner posts)
      translate([0, 0, IH - lip]) difference() {
        translate([lip_gap, lip_gap, 0]) cube([IW - 2*lip_gap, IL - 2*lip_gap, lip + 0.2]);
        translate([lip_gap + lip_t, lip_gap + lip_t, -1]) cube([IW - 2*(lip_gap + lip_t), IL - 2*(lip_gap + lip_t), lip + 2]);
        for (b = BOSSES) translate([b[0] - corner_skip/2, b[1] - corner_skip/2, -1]) cube([corner_skip, corner_skip, lip + 2]);
        // no lip where the ReSpeaker meets the connector wall
        translate([RS_X - 1, -1, -1]) cube([IW, 4, lip + 2]);
      }
      // radar slide-in holder: two grooved rails + an end stop
      radar_holder();
    }
    // lid screw holes
    for (b = BOSSES) translate([b[0], b[1], IH - 1]) cylinder(h = LID_T + 2, d = LID_SCREW_CLEAR);
    // camera hole with an outward viewing cone
    translate([CAM_C[0], CAM_C[1], IH - 1]) cylinder(h = LID_T + 2, d = CAM_HOLE_D);
    translate([CAM_C[0], CAM_C[1], IH + 0.6]) cylinder(h = LID_T - 0.6 + eps, d1 = CAM_HOLE_D, d2 = CAM_HOLE_FLARE);
    // honeycomb grille over the ReSpeaker
    translate([RS_X + 2, RS_Y + 2, IH - 1]) hexgrid(RS_W - 4, RS_L - 4, h = LID_T + 2, merge = GRILLE_MERGE);
  }
}

// ===================================================================== test plate
// Floor only, with short posts (full-height cookie posts + pins) and raised board outlines:
// screw both boards on to check hole positions before printing the full box.
module test_plate() {
  intersection() {
    base();
    translate([-WALL - 1, -WALL - 1, -FLOOR - 1]) cube([OW + 2, OL + 2, FLOOR + 1 + CK_POST_H + CK_T + PIN_PROUD + 0.2]);
  }
  translate([0, 0, 0]) linear_extrude(0.6) {
    difference() { translate([CK_X, CK_Y]) square([CK_W, CK_L]); translate([CK_X + 0.8, CK_Y + 0.8]) square([CK_W - 1.6, CK_L - 1.6]); }
    difference() { translate([RS_X, RS_Y]) square([RS_W, RS_L]); translate([RS_X + 0.8, RS_Y + 0.8]) square([RS_W - 1.6, RS_L - 1.6]); }
    translate(CAM_C) difference() { circle(d = CAM_D + 1.6); circle(d = CAM_D); }
  }
}

// ===================================================================== preview boards
module ghost_boards() {
  color("green", 0.6) translate([CK_X, CK_Y, CK_POST_H]) cube([CK_W, CK_L, CK_T]);
  color("dimgray", 0.6) translate([CK_X + 13, CK_Y + 10, CK_POST_H + CK_T]) cube([26, 68, CK_STACK - CK_T]);
  color("black") translate([CAM_C[0], CAM_C[1], CK_POST_H + CK_STACK]) cylinder(h = CAM_ABOVE_STACK, d = CAM_D);
  color("teal", 0.7) translate([RS_X, RS_Y, RS_POST_H]) cube([RS_W, RS_L, RS_T]);
  color("orange") translate([RADAR_C[0] - RADAR_W/2, RADAR_C[1] - RADAR_L/2, IH - RADAR_AIR - RADAR_T]) cube([RADAR_W, RADAR_L, RADAR_T]);
}

if (PART == "base") base();
else if (PART == "lid") translate([0, 0, IH + LID_T]) rotate([180, 0, 0]) translate([0, 0, -IH - LID_T]) lid();
else if (PART == "test") test_plate();
else { base(); ghost_boards(); color("lightblue", 0.35) translate([0, 0, 12]) lid(); }
