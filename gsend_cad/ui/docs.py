"""Help → Documentation: how to sketch, edit a sketch and make a solid from it."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QTextBrowser

from .. import APP_NAME
from . import theme

# (anchor, title in the contents list, HTML body). Keep this in step with the app: every key
# and button named here exists in this build.
SECTIONS = [
    ("start", "Getting Started", """
<h1>Getting Started</h1>
<p>{app} makes solid parts the way Fusion 360 does: draw a flat <b>sketch</b>, then
<b>extrude</b> its closed shapes into a solid. Every step lands in the <b>timeline</b> at the
bottom, so you can go back and change it.</p>
<h3>The screen</h3>
<table>
<tr><td class="k">CAD / CAM switch</td><td>Under the logo, top left. <b>CAD</b> (lit blue) shows the design tools; click it to flip to <b>CAM</b> for the toolpath tools (Milling / Turning tabs, being built). Click again to flip back.</td></tr>
<tr><td class="k">Ribbon (top)</td><td>Tools. <b>Solid</b> tab has Sketch and Extrude; <b>Utilities</b> has Export (STEP) and 3D Print (STL).</td></tr>
<tr><td class="k">Browser (left)</td><td>Bodies and sketches in the part, and the part's size, volume and weight.</td></tr>
<tr><td class="k">3D view (middle)</td><td>The part. View cube and Home button at the top right.</td></tr>
<tr><td class="k">Status bar</td><td>Cursor X / Y / Z and a hint for what to do next. Read it when stuck.</td></tr>
<tr><td class="k">Timeline (bottom)</td><td>Every sketch and feature, in order.</td></tr>
</table>
<p><b>Panels</b> (Rotate, a toolpath, the Sketch Palette...): drag the blue title bar to move one out of the
way. It stays there, and a panel with the same name opens there again until the app is closed.</p>
<h3>Moving the view</h3>
<table>
<tr><td class="k">Left drag</td><td>Selection box. Left to right picks what's wholly inside (solid box); right
to left picks anything it touches (dashed green box). Bodies in the view; sketch shapes while sketching (Select,
Rotate, Mirror, Pattern). Ctrl adds to what's picked. Delete removes them all. While a command like Extrude or a
toolpath is open, left drag orbits as before.</td></tr>
<tr><td class="k">Left click</td><td>Picks the body under it (Ctrl: add / drop); empty space clears.</td></tr>
<tr><td class="k">Shift + left drag</td><td>Orbit (spin the part)</td></tr>
<tr><td class="k">Shift + wheel-button drag</td><td>Orbit freely in any direction. Works while sketching too (left click draws there).</td></tr>
<tr><td class="k">Right drag</td><td>Pan</td></tr>
<tr><td class="k">Wheel-button drag</td><td>Pan</td></tr>
<tr><td class="k">Mouse wheel</td><td>Zoom (toward you zooms in)</td></tr>
<tr><td class="k">Home key</td><td>Back to the home view</td></tr>
</table>
<h3>Right-click in the view: Direct View / Rotate View</h3>
<ul>
<li>Right-click empty space (a click, not a drag; right-drag still pans).</li>
<li><b>Direct View</b> turns to the nearest straight view (Top, Bottom, Front, Back, Left, Right, named in
the menu), keeping your zoom and centre. Handy after orbiting when you can't quite get it square.</li>
<li><b>Rotate View Clockwise / Counterclockwise</b> spins the view 90° about your line of sight.</li>
</ul>
<h3>Settings → View projection</h3>
<ul>
<li><b>Orthographic</b> (default): straight, no perspective. Edges stay parallel, so FRONT / RIGHT / TOP look
like a drawing.</li>
<li><b>Perspective</b>: things further away look smaller, like a photo.</li>
<li><b>Perspective with ortho faces</b>: perspective, but TOP / FRONT / LEFT / RIGHT (view cube) are straight;
orbiting away goes back to perspective.</li>
<li>Sketches always look straight down. The choice is remembered next time.</li>
</ul>
<h3>Start a new part</h3>
<p><b>FILE → New</b> (or <b>Ctrl+N</b>, or the page icon next to FILE) gives an empty part.
Then: <b>L</b> to sketch, draw a closed shape, <b>Enter</b>, <b>E</b> to make it solid (see
<b>Create a Sketch</b> and <b>Make a Solid</b>). <b>Ctrl+S</b> saves it; the first save asks for
a name.</p>
<p class="tip">Units are inches. The demo part (Bracket Plate) opens on start so there is
something to look at. FILE → New replaces it with an empty part.</p>
"""),
    ("sketch", "Create a Sketch", """
<h1>Create a Sketch</h1>
<ol>
<li>Press <b>L</b> (or <b>Solid → Sketch</b>). The view turns to look straight down on the XY
plane, the <b>SKETCH</b> tab opens, and the <b>Sketch Palette</b> appears on the right.</li>
<li><b>Sketch on the part.</b> With a body on screen, Sketch (or <b>L</b>) first asks for a face:
move over any flat face of the part and it is outlined, click it and the sketch opens on that face,
looking square on. Click empty space or press <b>Enter</b> to sketch on the XY plane instead;
<b>Esc</b> cancels. The palette's <b>Plane</b> field then slides the sketch off that face.</li>
<li><b>Snap points.</b> While drawing, the cursor jumps to the ends, midpoints and centers of what
is already in the sketch, to the origin, and to the part's edges that lie on the sketch plane
(drawn dimmed). A small diamond marks the point and the tag says END, MID or CENTER. Away from
one, the grid snap applies as usual.</li>
<li><b>Set the height first</b> if the sketch belongs on top of something: in the palette,
set <b>Plane</b> to the Z height. Example: the demo plate is 0.5 thick, so <b>Plane 0.5</b>
draws on its top face. Leave it at 0 to draw on the bottom (XY) plane.</li>
<li>Pick a tool and click in the view:
<table>
<tr><td class="k">Line &nbsp;<b>L</b></td><td>Click start, click end. Keep clicking to chain lines. <b>Esc</b> ends the chain. Within 10° of level or plumb the line is held dead straight (the cursor tag says HORIZONTAL / VERTICAL); hold <b>Ctrl</b> to draw at any angle.</td></tr>
<tr><td class="k">Rectangle &nbsp;<b>R</b></td><td>Click one corner, then the opposite corner.</td></tr>
<tr><td class="k">Center Rect</td><td>Click the center, then a corner (ribbon button).</td></tr>
<tr><td class="k">Circle &nbsp;<b>C</b></td><td>Click the center, then a point on the circle.</td></tr>
<tr><td class="k">Polygon &nbsp;<b>P</b></td><td>Click the center, then a corner. Set the number of sides in the palette first.</td></tr>
<tr><td class="k">Point</td><td>Click once. A reference point (later: hole centers). Never part of a profile.</td></tr>
</table>
The blue tag next to the cursor shows the size as you move (width × height, Ø, length).</li>
<li>Press <b>Enter</b> (or <b>Finish Sketch</b>). The sketch is added to the timeline as
<b>Sketch1</b>, <b>Sketch2</b>, and so on.</li>
</ol>
<h3>Exact sizes and positions (from the origin)</h3>
<ul>
<li>Every position is measured from the <b>origin</b> (X0 Y0, where the red and green axes meet).</li>
<li>A shape you just drew is <b>selected</b>: the palette shows its values. Click a value, type
the exact number, press <b>Enter</b> (<b>Tab</b> goes to the next one). The shape updates at once.</li>
<li>Or <b>right-click a dimension in the view</b> (its number, or its line): a box opens on it with
the value selected. Type the new one, <b>Enter</b>. <b>Esc</b> closes it unchanged.</li>
<li><b>Rectangle:</b> X / Y of its lower-left corner (Center Rect: of its center), Width, Height,
Corner R. <b>Circle:</b> center X / Y, Diameter. <b>Line:</b> X / Y (moves the whole line, it stays at its angle), End X / Y (moves the end only), Length,
Angle (Length and Angle keep the start where it is). <b>Polygon:</b> center X / Y, Radius, Sides,
Angle. <b>Point:</b> X / Y.</li>
<li>To change a shape later: press <b>Esc</b> until the banner says <b>SELECT</b> (or click
<b>Select</b>), then click the shape's outline in the view, or click its row in the palette list.</li>
<li>The selected shape is white and shows its dimensions: <b>X</b> and <b>Y</b> from the origin,
and its size. Tick <b>Dimensions: All</b> to see every shape's dimensions at once.</li>
<li><b>Delete</b> removes the selected shape. <b>Ctrl+Z</b> undoes a typed value too.</li>
</ul>
<h3>Snapping and accuracy</h3>
<ul>
<li><b>Grid snap</b> is on, at 0.250 in. Change <b>Snap size</b> in the palette (0.125, 0.0625, 0.010).</li>
<li>Hold <b>Shift</b> while clicking to snap four times finer.</li>
<li>Untick <b>Grid snap</b> to place points freely.</li>
</ul>
<h3>Fixing mistakes while sketching</h3>
<ul>
<li><b>Ctrl+Z</b> or <b>Undo</b> undoes the last change (a shape, a typed value, a delete); <b>Ctrl+Y</b> redoes it.</li>
<li>Click <b>×</b> next to any shape in the palette list to delete that one.</li>
<li><b>Clear</b> removes everything; <b>Cancel</b> leaves without keeping the sketch.</li>
<li><b>Esc</b> drops a half-drawn shape; press it again to put the tool down.</li>
<li><b>Right-click</b> (without dragging) while drawing: <b>Done</b> puts the tool down (ends a line chain),
<b>Cancel this shape</b> drops the half-drawn one, <b>Finish Sketch</b>. Right drag still pans.</li>
</ul>
<h3>Round or bevel a corner (Fillet / Chamfer in the sketch)</h3>
<ul>
<li>Set the size in the palette: <b>Fillet R</b> for Fillet, <b>Chamfer H</b> (along X) and
<b>Chamfer V</b> (along Y) for Chamfer.</li>
<li>Click <b>Fillet</b> or <b>Chamfer</b> (Sketch tab, Modify), then click a sharp corner. A white ring
shows which corner a click will change. Keep clicking corners; each one is its own Ctrl+Z.</li>
<li>A rectangle or polygon is split into lines when you round one of its corners (like Fusion).
Extrudes already made from it keep working.</li>
<li>The new fillet or chamfer is selected, so its size can be typed: the fillet's <b>Radius</b>, or the
chamfer's <b>Horizontal</b> and <b>Vertical</b> legs. Its dimensions show them too; right-click one to
change it. The corner stays put: the two sides are trimmed back to the new size and nothing else moves.</li>
</ul>
<h3>Polygon: sides, across flats / across corners</h3>
<ul>
<li>Set <b>Polygon sides</b> (3 to 64) and <b>Polygon size</b> in the palette, then click the center and drag:
with <b>Across flats</b> the second click is the middle of a flat (a hex drawn 1/2 out is 1.0 across flats);
with <b>Across corners</b> it's a corner.</li>
<li>Click the polygon to type its <b>Across flats</b> or <b>Across corners</b> exactly (the other follows), its
sides, center X / Y and angle. Its dimensions show AF and AC; right-click one to change it.</li>
</ul>
<h3>Rotate, Mirror, Pattern</h3>
<ul>
<li>Pick the tool (Sketch tab, Modify), then click the shapes to work on (they turn blue; click again to
drop one). A shape that was selected is picked already. The result shows faintly; <b>OK</b> or Enter applies,
<b>CANCEL</b> or Esc puts the tool down. Each one is a single Ctrl+Z.</li>
<li><b>Rotate</b>: angle (counter-clockwise +), center (type X / Y or click the arrow then a point in the
sketch; it snaps to ends and centers). <b>Keep original</b> makes a turned copy instead.</li>
<li><b>Mirror</b>: across the Y axis, the X axis or a line in the sketch (click the arrow, then the line).
Keeps the original by default.</li>
<li><b>Pattern</b>: <b>Circular</b> = count and angle about a center (360 = evenly all the way round, e.g. a bolt
circle; less = from the original to that angle). <b>Rectangular</b> = count and spacing in X and Y.</li>
<li>A rectangle turned by an odd angle becomes its four lines (so it can still be edited line by line).</li>
</ul>
<h3>Trim</h3>
<ul>
<li>Click <b>Trim</b> (Sketch tab, Modify) or press <b>T</b>. Hover a line, arc or circle: the piece a click
will cut away turns red. It runs to the nearest crossing on each side of the cursor.</li>
<li>A piece with nothing crossing it is removed entirely. A circle needs two crossings to be trimmed
into an arc. A rectangle or polygon is split into lines first. Each click is its own Ctrl+Z.</li>
</ul>
<h3>Closed shapes (what can be extruded)</h3>
<p>Only closed shapes can become solid: a rectangle, circle, polygon, or lines that join
end to end back to the start. A shape drawn <b>inside</b> another becomes a hole in it, so a
rectangle with a circle inside gives two pickable areas: the ring between them, and the
circle.</p>
"""),
    ("edit", "Edit a Sketch", """
<h1>Edit a Sketch</h1>
<p>A finished sketch can be opened again to add shapes, delete shapes, or move it up or
down.</p>
<h3>Open it</h3>
<ul>
<li><b>Timeline:</b> right-click the sketch icon → <b>Edit Sketch</b> (or double-click it).</li>
<li><b>Browser:</b> open <b>Sketches</b>, then right-click the sketch → <b>Edit Sketch</b> (or double-click it).</li>
</ul>
<p>The sketch opens with the <b>EDIT SKETCH</b> palette, and its shapes are listed there.</p>
<h3>Change it</h3>
<ul>
<li><b>Add</b> shapes with the same tools as a new sketch (L, R, C, P).</li>
<li><b>Delete</b> a shape: click <b>×</b> next to it in the palette list.</li>
<li><b>Move the whole sketch up or down:</b> change <b>Plane</b> in the palette.</li>
</ul>
<h3>Save or throw away</h3>
<ul>
<li><b>Enter</b> or <b>Finish Sketch</b> saves the changes. Extrudes made from this sketch
rebuild on their own, so moving the plane moves the solid with it.</li>
<li><b>Cancel</b> leaves the sketch the way it was.</li>
<li>Saved and changed your mind? <b>Ctrl+Z</b> puts the old sketch back.</li>
</ul>
<p class="warn">If you delete a shape that an extrude was made from, that extrude can't find
its profile and turns <b>red</b> in the timeline. Press Ctrl+Z, or delete the red extrude and
extrude again.</p>
<p class="tip">New shapes you add to an edited sketch are not added to old extrudes. Press
<b>E</b> and pick them to make them solid.</p>
"""),
    ("hide", "Hide / Show a Sketch", """
<h1>Hide / Show a Sketch</h1>
<p>A sketch hides by itself once it is extruded. Any sketch can also be hidden or shown by
hand, for example a construction sketch drawn on a face that you don't need to see any more.</p>
<ul>
<li><b>Browser:</b> under <b>Sketches</b>, right-click the sketch → <b>Hide Sketch</b> /
<b>Show Sketch</b>. Or click the <b>dot</b> left of its name (blue = shown, hollow = hidden).</li>
<li><b>Timeline:</b> right-click the sketch → <b>Hide Sketch</b> / <b>Show Sketch</b>.</li>
</ul>
<p>Hidden sketches stay in the part and are saved with it. Their shapes can't be picked by
Extrude until you show the sketch again.</p>
"""),
    ("rename", "Rename / Delete", """
<h1>Rename and Delete</h1>
<p>Works on sketches and bodies in the <b>Browser</b> (left).</p>
<h3>Rename</h3>
<ul>
<li>Right-click the sketch or body → <b>Rename</b> (or click it and press <b>F2</b>).</li>
<li>Type the new name and press <b>Enter</b>. <b>Esc</b> keeps the old name.</li>
</ul>
<p>Names are saved in the .gcad file. Two sketches can't share a name.</p>
<h3>Delete</h3>
<ul>
<li>Click the sketch or body in the Browser and press <b>Delete</b>, or right-click →
<b>Delete</b>.</li>
<li><b>Sketch:</b> if an extrude was made from it, {app} asks first and deletes both
(otherwise the extrude would have nothing to build from).</li>
<li><b>Body:</b> a <b>Remove</b> step is added to the timeline, like Fusion. Roll the
timeline back before it to see the body again.</li>
<li><b>Ctrl+Z</b> brings back anything you deleted.</li>
</ul>
<p class="tip">Any step in the timeline can also be deleted: right-click it → Delete.</p>
"""),
    ("extrude", "Make a Solid (Extrude)", """
<h1>Make a Solid from a Sketch (Extrude)</h1>
<ol>
<li>Finish the sketch (<b>Enter</b>).</li>
<li>Press <b>E</b> (or <b>Solid → Extrude</b>). The <b>EXTRUDE</b> panel opens on the right.</li>
<li><b>Pick the profile:</b> move over the sketch; closed areas light up blue. Click one to
select it; click more to add them; click a selected one again to remove it. If the newest
sketch has only one closed area, it is already picked.</li>
<li>Set the options:
<table>
<tr><td class="k">Distance</td><td>How far to extrude, in inches. A negative number goes down.</td></tr>
<tr><td class="k">Direction</td><td><b>One side</b> goes up from the sketch plane. <b>Symmetric</b> splits the distance above and below it.</td></tr>
<tr><td class="k">Operation</td><td><b>Join</b> adds to the part. <b>Cut</b> removes material (a pocket or a hole). <b>New Body</b> makes a separate solid.</td></tr>
</table>
The preview updates as you type: blue for Join / New Body, red for Cut.</li>
<li>Click <b>OK</b> (or press <b>Enter</b>). <b>Esc</b> or <b>Cancel</b> backs out.</li>
</ol>
<h3>Example: a pocket with a pin left standing</h3>
<ol>
<li><b>L</b>, then <b>Plane 0.5</b> (top of the demo plate).</li>
<li><b>R</b>: a 2 × 1.5 rectangle on the plate. <b>C</b>: a Ø0.5 circle inside it. <b>Enter</b>.</li>
<li><b>E</b>, click the ring between the rectangle and the circle.</li>
<li>Operation <b>Cut</b>, Distance <b>-0.25</b>, <b>OK</b>. VOLUME in the Browser drops.</li>
</ol>
<h3>Example: a boss on top</h3>
<ol>
<li><b>L</b>, <b>Plane 0.5</b>, <b>C</b>: a circle on the plate, <b>Enter</b>.</li>
<li><b>E</b>, Operation <b>Join</b>, Distance <b>0.75</b>, <b>OK</b>.</li>
</ol>
<p class="tip">For a Cut from the top face, use a negative distance so it goes down into
the part, or use <b>Symmetric</b>.</p>
"""),
    ("revolve", "Revolve (turned parts)", """
<h1>Revolve: spin a cross-section into a round part</h1>
<ol>
<li>Sketch <b>half</b> the part's cross-section on one side of the axis it turns about. For a lathe
part, draw above the sketch's X axis: X along the part, Y = radius. A bore is just a profile that
starts above the axis (Y = bore radius) instead of on it.</li>
<li>Finish the sketch, then <b>Solid → Revolve</b>. Click the profile(s) to spin.</li>
<li>Pick the <b>Axis</b>: <b>Sketch X axis</b>, <b>Sketch Y axis</b>, or any line you drew in that sketch
(it shows as a yellow line). It starts on X when the profile sits above X.</li>
<li><b>Angle</b> 360° for a full part (less for a partial one). <b>Operation</b>: Join, Cut (e.g. a
groove), or New Body. <b>OK</b> or Enter.</li>
</ol>
<p class="tip">The profile must not cross the axis; it may touch it.</p>
"""),
    ("fillet", "Fillet / Chamfer Solid Edges", """
<h1>Round or bevel edges of the solid</h1>
<ol>
<li><b>Solid → Fillet</b> (or press <b>F</b>) to round, <b>Solid → Chamfer</b> to bevel. You can switch
between them in the panel's <b>Type</b>.</li>
<li>Click the edges (they light up white under the cursor, blue when picked). Click again to un-pick.
Left drag still orbits.</li>
<li>Set the <b>Radius</b> (Fillet) or <b>Distance</b> (Chamfer), then <b>OK</b> or Enter.</li>
</ol>
<ul>
<li>An edge that runs smoothly into a rounded one takes the whole smooth run with it (Fusion's
"tangent chain"), so the edge treatment wraps around corners.</li>
<li>If the size is too big for the faces next to the edge, the feature shows red in the timeline with the
reason; Ctrl+Z, or edit the size smaller.</li>
</ul>
"""),
    ("setup", "CAM: Create a Setup", """
<h1>CAM Setup: Milling or Turning</h1>
<p>A setup says how the part is held and machined: the machine type, the stock around the part and
where the work zero (WCS) is. Toolpaths will belong to a setup.</p>
<ol>
<li>Flip the switch under the logo to <b>CAM</b>. Click <b>Setup</b> (Milling or Turning tab).</li>
<li>At the top of the panel pick <b>MILLING</b> or <b>TURNING</b> (it starts on the tab you came from).</li>
<li><b>Part</b>: all bodies, or one body.</li>
<li><b>Stock</b>: <b>Stock per side</b> (extra material around the part) or <b>Fixed size</b> (the real blank: width / length / height, or bar diameter / length). Switching to Fixed size fills in the part plus the per-side stock, rounded up to 1/8"; stock smaller than the part is refused.</li>
<li><b>Milling</b>: stock added on the <b>sides</b>, <b>top</b> and <b>bottom</b> of the part's box, and the
<b>WCS origin</b>: stock top center, stock top front-left corner, or the model origin. Z points up.</li>
<li><b>Turning</b>: the <b>spindle axis</b> (it guesses the axis the part is round about), which end is the
<b>front</b> (toward the tool), bar stock on the <b>OD</b> (per side), <b>front face</b> and
<b>chuck side</b>, and where <b>Z0</b> is: stock front face or part front face. Z runs along the spindle.</li>
<li><b>Pick the origin in the view</b> (milling): click <b>PICK IN VIEW</b> (or choose WCS origin → Picked
point). Hover the part, the stock or a point you drew in a CAD sketch: endpoints, midpoints, circle centers,
stock corners, stock edge midpoints and stock face centers light up with their name. Click one: X0 Y0 Z0 goes
there. Esc stops picking.</li>
<li><b>X axis points</b>: which way the WCS +X runs (model +X, −X, +Y or −Y). The WCS turns about Z so it stays a
real machine coordinate system: −X also flips Y (a 180° turn), ±Y turns it 90°. Toolpaths and G-code follow.</li>
<li>The yellow outline is the stock; the arrows are the WCS (red X, green Y, blue Z). <b>OK</b> or Enter.</li>
</ol>
<ul>
<li>Setups are listed under <b>Setup/Operation</b> in the Browser. Double-click one to change it; Delete
removes it (Ctrl+Z brings it back); F2 renames it. Click one to show its stock.</li>
<li>Setups are saved in the .gcad file. They don't change the design timeline.</li>
</ul>
"""),
    ("face", "CAM: Face Operation", """
<h1>Face</h1>
<p>Faces the stock down to the part (plus any stock to leave). Make a Setup first.</p>
<ol>
<li>CAM → <b>Face</b> (Milling or Turning tab). It opens on the setup you last picked, or a setup
of the tab's type (pick a setup in the Browser first to choose another). It's named Face (a second one Face2, then Face3...)
(rename it in the Browser).</li>
<li><b>Tool</b>: picked from the Tool Library (the tools that fit, e.g. face and end mills). <b>New tool…</b>
at the bottom of the list opens the library with a new tool ready to fill in.</li>
<li><b>Milling setup</b>: stepover % of the tool, max stepdown, stock
to leave, cut direction (along X or Y), spindle RPM (with an SFM box beside it: type either, the other is worked out from the tool Ø, SFM = RPM × π × Ø ÷ 12; same on 2D Contour and Drill) and feed (in/min). Zigzag passes run fully off
the stock at both ends, from the stock top down to the part top.</li>
<li><b>Turning setup</b>: max stepdown per pass, stock to leave, how far past center (X, radius), surface
speed SFM, feed in/rev and max RPM. Each pass feeds from outside the bar in past center, then rapids
back, from the bar's front face down to the part face.</li>
<li><b>Output</b> (turning): <b>Single lines (G01)</b> writes every move, <b>Canned cycle (G72)</b> writes a G72
facing cycle with the finished face as its contour (N blocks: Z down to the face, then X past center); D (Haas) or
the first G72 line (Fanuc) is the depth per pass, W the stock to leave.</li>
<li>The toolpath shows live (blue = cutting, yellow = rapid) with the number of passes and a rough
cutting time. <b>OK</b> or Enter.</li>
</ol>
<ul>
<li>The operation is listed under its setup in the Browser. Double-click to change it, Delete to remove,
F2 to rename. Clicking an operation shows its path bright; the setup's other paths are dim.</li>
<li>Each operation has a <b>Tool number</b> (T1, T0101 on a lathe) used by the post.</li>
</ul>
"""),
    ("rough", "CAM: Roughing (turning, OD or ID)", """
<h1>Roughing</h1>
<p>Roughs a turned part down to its shape plus stock to leave: the outside (OD), or with
<b>Internal (ID)</b> ticked the inside (boring the ID). Needs a Turning setup.</p>
<ol>
<li>CAM → Turning tab → <b>Roughing</b>.</li>
<li><b>Internal (ID)</b>: off = OD. On = bore: passes go into the hole at growing diameters, starting from the
<b>Drilled hole Ø</b> (0 = auto: the smallest bore along the path is taken as already drilled) and stopping
where the bore gets smaller than that. Pull-offs go toward the center; a bigger bore behind a smaller one
(an undercut) is skipped. G71 output puts the ID stock in a negative U. Same box on turning <b>Contour</b>.</li>
<li><b>Depth of cut (side)</b> per pass (radius), <b>Stock to leave X</b> (per side) and <b>Z</b> (on shoulders),
<b>Pull-off</b> (the 45° lift at the end of each
pass), surface speed SFM, feed in/rev, max RPM.</li>
<li><b>Start</b> / <b>End</b>: click the arrow button, then click an edge or end point of the part. The toolpath
starts (or stops) at that Z; white rings in the view show where, and the button turns blue (hover it for
the Z). Right-click the button to go back to the part's front face / back end. The <b>Extend</b> box on the
same line runs it that much further. Same on turning <b>Contour</b>.</li>
<li>Passes run along Z toward the chuck at falling diameters, each stopping where it meets the part
(plus stock to leave), then a last pass follows the profile to take off the steps. Grooves and
undercuts are skipped: an OD tool can't reach into them.</li>
<li><b>Output</b>: <b>Single lines (G01)</b> writes every move; <b>Canned cycle (G71)</b> writes a G71 with the
finished contour in N-blocks (Haas: one line with D; Fanuc: two G71 lines). U / W carry the stock to leave.</li>
</ol>
"""),
    ("finish", "CAM: Contour (turning finish)", """
<h1>Contour (turning)</h1>
<p>One pass along the part's outside (or, with <b>Internal (ID)</b> ticked, along the bore) from the front
to the back, usually the finish pass after Roughing. Needs a Turning setup.</p>
<ol>
<li>CAM → Turning tab → <b>Contour</b>. Set the tool, <b>Stock to leave X / Z</b> (0 = finished size; set
some to use it as a semi-finish), <b>Start</b> / <b>End</b> (arrow button, pick on the part) each with an <b>Extend</b>,
pull-off, SFM, feed in/rev and max RPM.</li>
<li><b>Use G70 cycle</b> ticked: the post writes <b>G70 P Q</b> over the contour blocks of the last Roughing
with G71 output in the same setup (the usual rough-then-finish program, with its own tool change). With
no such rough, the Contour is posted line by line with a note saying so.</li>
<li>Unticked: every move is written line by line (G01).</li>
</ol>
"""),
    ("groove", "CAM: Groove (turning: OD, ID or face)", """
<h1>Groove</h1>
<p>Plunge-grooves the grooves in a turned part. Needs a Turning setup and a grooving insert in the
Tool Library (type <b>Grooving</b>; its <b>Width</b> is the insert width).</p>
<ol>
<li>CAM → Turning tab → <b>Groove</b>. <b>Groove</b>: <b>External (OD)</b>, <b>Internal (ID)</b> (in the bore) or
<b>Face</b> (a ring cut into the front face).</li>
<li>Grooves are found in the model: any dip with metal on both sides. A step open to one end isn't a
groove (that's Roughing's job). OD / ID: <b>Start</b> / <b>End</b> limit which grooves along Z (pick on the part).</li>
<li>Plunges side by side, <b>Stepover % of width</b> apart, from one wall to the other. Each plunge stops on
the highest metal under the insert plus <b>Stock to leave</b>, so a shaped groove comes out stepped,
never gouged. <b>Peck</b> &gt; 0 pecks with a short pull back to break the chip.</li>
<li>The programmed point is the insert's front corner (OD / ID) or its outer corner (Face): touch it
off that way. ID grooves go in and out through the bore below its smallest Ø.</li>
<li>Posted line by line (G01).</li>
</ol>
"""),
    ("drill", "CAM: Drill (mill and lathe)", """
<h1>Drill</h1>
<p>Drills the round holes in your model. Model the hole in CAD (a circle cut through or partway),
then CAM → <b>Drill</b> (Milling tab: Drilling; Turning tab: Turning).</p>
<ol>
<li><b>Milling</b>: <b>Holes</b> lists every hole size found opening up (+Z); pick one (a library drill of that size is picked
when there is one) or All holes. Holes are drilled nearest first, returning to the clearance height between
holes (G98).</li>
<li><b>Turning</b>: drills the hole on the spindle axis that opens at the front face, at a fixed RPM (G97)
and feed in/rev.</li>
<li><b>Cycle</b>: Drill (G81), Peck (G83, full retract each peck Q) or, on a mill, Chip break (G73).</li>
<li>Blind holes are drilled to the hole's bottom. Through holes go the <b>Breakthrough</b> plus the
drill's 118° point further. <b>R plane</b> is how far above the hole (or off the face) the feed starts.</li>
<li><b>Milling, select holes</b>: the arrow button beside <b>Holes</b>, then click holes in the view (grey rings):
a click picks one (blue), a second click drops it. Only the picked holes are drilled, e.g. one of four 1/2 holes,
or a mix of sizes to center drill. Esc or the button stops selecting; picking a size in the list goes back
to drilling by size.</li>
<li><b>Depth</b>: drill the point this far below the hole's top instead (0 = to the modelled hole).</li>
<li><b>Turning Start / End</b>: click the cursor button, then an edge or end point of the part, to start or stop
the drill there (right-click the button: back to the hole). <b>Extend</b> goes that much further. With a Depth
or an End you can drill on center even without a hole modelled.</li>
<li>Post: mill G81 / G83 / G73 then G80. Haas lathe: G81 / G83 on center. Fanuc lathe: the pecks are
written out as G01 / G00 (lathe drilling cycles differ between Fanuc controls).</li>
</ol>
"""),
    ("tools", "CAM: Tool Library", """
<h1>Tool Library</h1>
<p>Your cutting tools, saved on this computer and shared by every part. Operations pick their tool here.</p>
<ol>
<li>CAM → <b>Tool Library</b> (Setup group), or <b>New tool…</b> at the bottom of an operation's
Tool list.</li>
<li><b>Machine</b>: Milling or Turning, each with its own list (in T-number order).</li>
<li><b>NEW TOOL</b> adds one; set its <b>Number</b> (the T number on the machine), <b>Name</b>, <b>Type</b> (face mill,
end mill, drill; OD turning insert or drill on a lathe) and <b>Diameter</b> (or <b>Nose radius</b> for an insert).
Changes save straight away. <b>DELETE</b> removes the selected tool.</li>
<li>An operation copies its tool (number, size, name), so a saved part posts the same even if the library
changes later. An op whose tool is no longer in the library shows it as "(not in library)".</li>
</ol>
"""),
    ("contour", "CAM: 2D Contour and Simulate", """
<h1>2D Contour (milling)</h1>
<ol>
<li>CAM → <b>2D Contour</b> (needs a Milling setup). The outline is found from the part: its outside as
seen from above, including bosses and flanges higher up.</li>
<li><b>Tool</b> (an end mill from the Tool Library), <b>max stepdown</b>, <b>wall stock</b> to leave, <b>below part bottom</b>
(extra depth to clean the floor edge), <b>cut direction</b> (Climb = clockwise around the outside with
M03, or Conventional), <b>lead in / out</b> distance, spindle RPM, feed and <b>plunge</b> feed.</li>
<li>Passes step down from the stock top to the part bottom. Each pass plunges beside the part
(on the lead), goes around, and leaves the same way. The start is the middle of the longest side.</li>
</ol>
<p class="tip">Arcs are written as short G01 lines for now (within 0.0005"). G02 / G03 arcs are coming.</p>
<h1>Simulate</h1>
<ul>
<li>Right-click an operation (or a whole setup) in the Browser → <b>Simulate</b>, or CAM → <b>Simulate</b>.</li>
<li>▶ plays at the programmed feeds (rapids assumed 400 in/min), times 1 to 100 speed. Drag the slider to
scrub. Space = play / pause, Esc closes. The readout shows where the tool is, which move, and the time.</li>
<li>This checks the motion. For material removal, load the posted program into G-SEND.IO's simulator.</li>
</ul>
<p>Right-click an operation or setup → <b>Post Process…</b> opens the G-code window on that setup.</p>
"""),
    ("post", "CAM: Post Process (G-code)", """
<h1>Post Process: G-code out</h1>
<ol>
<li>CAM → <b>Post Process</b>. Pick the <b>Setup</b> (all its operations are posted, in order).</li>
<li><b>Control</b>: Haas or Fanuc (generic). <b>Program</b> number (O1000 …), <b>Work offset</b> (G54-G59),
<b>Coolant</b> M08 on/off. The code updates as you change them.</li>
<li><b>SAVE .NC…</b> writes the file (Windows line ends, ready for USB / DNC). The settings are remembered
with the setup and saved in the .gcad file.</li>
</ol>
<ul>
<li><b>Mill</b>: G20 G17 G40 G49 G80 G90 · T M06 · offset · S M03 · G43 H tool length · M08 · the cut ·
M09 M05 · G28 G91 Z0. then Y0. (Haas) or X0. Y0. (Fanuc) · M30.</li>
<li><b>Lathe</b>: G20 G18 G40 G80 G99 · G28 U0. W0. · T0101 · offset · G50 max RPM · G96 SFM M03 · X is
<b>diameter</b> · M09 M05 · G28 U0. W0. · M30.</li>
<li>Inch, absolute, only changed words written (modal). Always prove out a new program: single block,
rapid override down, and check it in G-SEND.IO's simulator first.</li>
</ul>
"""),
    ("timeline", "Timeline, Undo, Files", """
<h1>Timeline, Undo and Files</h1>
<h3>Timeline</h3>
<ul>
<li>Click a feature to <b>roll back</b> to it; later features grey out. Click the last one
(or ⏭) to go forward again. ▶ plays the whole history.</li>
<li>New features are inserted at the blue marker, so you can roll back and add something
earlier.</li>
<li>Right-click a feature → <b>Delete</b>. <b>Ctrl+Z</b> brings it back.</li>
<li>A <b>red</b> feature failed to build; hover it to see why.</li>
</ul>
<h3>Undo / redo</h3>
<p><b>Ctrl+Z</b> undo, <b>Ctrl+Y</b> redo (also the arrows in the top bar).</p>
<h3>Files</h3>
<table>
<tr><td class="k">Ctrl+N</td><td>New, empty part (asks to save unsaved work first).</td></tr>
<tr><td class="k">Ctrl+S</td><td>Save the part as a <b>.gcad</b> file (keeps the full timeline).</td></tr>
<tr><td class="k">Ctrl+Shift+S</td><td>Save As: a copy under a new name.</td></tr>
<tr><td class="k">Ctrl+O</td><td>Open a .gcad file.</td></tr>
<tr><td class="k">FILE → Export STEP</td><td>STEP file, for Fusion 360 or any CAM system (also Utilities → Export).</td></tr>
<tr><td class="k">Utilities → 3D Print</td><td>STL file.</td></tr>
</table>
"""),
    ("keys", "Keyboard Shortcuts", """
<h1>Keyboard Shortcuts</h1>
<table>
<tr><td class="k">F12 / Print Screen</td><td>Screenshot of the whole screen, open menus included: copied to the
clipboard (paste it straight into a chat or email) and saved in Pictures → G-SEND Screenshots. Use it
instead of the Snipping Tool, which closes G-SEND's menus before it can take them.</td></tr>
<tr><td class="k">L</td><td>New sketch (in a sketch: Line)</td></tr>
<tr><td class="k">R / C / P</td><td>Rectangle / Circle / Polygon (in a sketch)</td></tr>
<tr><td class="k">Shift + click</td><td>Snap 4× finer</td></tr>
<tr><td class="k">Enter</td><td>Finish sketch / OK in Extrude</td></tr>
<tr><td class="k">Esc</td><td>Drop the current shape / end a line chain / cancel Extrude</td></tr>
<tr><td class="k">E</td><td>Extrude</td></tr>
<tr><td class="k">F</td><td>Fillet solid edges</td></tr>
<tr><td class="k">Ctrl+Z / Ctrl+Y</td><td>Undo / redo</td></tr>
<tr><td class="k">Ctrl+N</td><td>New part</td></tr>
<tr><td class="k">Ctrl+S / Ctrl+O</td><td>Save / open (Ctrl+Shift+S = Save As)</td></tr>
<tr><td class="k">Home</td><td>Home view</td></tr>
<tr><td class="k">Delete</td><td>Delete the sketch or body picked in the Browser</td></tr>
<tr><td class="k">F2</td><td>Rename the sketch or body picked in the Browser</td></tr>
<tr><td class="k">F1</td><td>This documentation</td></tr>
</table>
<p class="tip">Hole and some other ribbon tools are not in this build yet; clicking them says so.</p>
"""),
]


def html() -> str:
    body = "".join(f'<a name="{a}"></a>{h.format(app=APP_NAME)}<hr>' for a, _t, h in SECTIONS)
    return f"<html><body>{body}</body></html>"


def css() -> str:
    t = theme
    return f"""
body {{ color: {t.FG}; font-size: 13px; }}
h1 {{ color: {t.ACCENT}; font-size: 20px; font-weight: 700; margin-top: 4px; }}
h3 {{ color: {t.FG}; font-size: 14px; font-weight: 700; margin-top: 14px; margin-bottom: 4px; }}
p, li {{ color: {t.FG}; line-height: 140%; }}
b {{ color: {t.ACCENT}; font-weight: 600; }}
td {{ padding: 3px 10px 3px 0; vertical-align: top; }}
td.k {{ color: {t.FG2}; white-space: nowrap; }}
p.tip {{ color: {t.FG2}; border-left: 2px solid {t.ACCENT}; padding-left: 8px; }}
p.warn {{ color: {t.WARN}; }}
hr {{ color: {t.LINE}; }}
"""


class DocsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("docs")
        self.setWindowTitle(f"{APP_NAME} · Documentation")
        self.setWindowIcon(theme.app_icon())
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(940, 660)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.toc = QListWidget()
        self.toc.setFixedWidth(220)
        for _a, title, _h in SECTIONS:
            self.toc.addItem(title.upper())
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.document().setDefaultStyleSheet(css())
        self.text.document().setDocumentMargin(18)
        self.text.setHtml(html())
        lay.addWidget(self.toc)
        lay.addWidget(self.text, 1)
        self.toc.currentRowChanged.connect(self.go)
        self.toc.setCurrentRow(0)

    def go(self, row: int):
        if 0 <= row < len(SECTIONS):
            self.text.scrollToAnchor(SECTIONS[row][0])
