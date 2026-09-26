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
<tr><td class="k">Ribbon (top)</td><td>Tools. <b>Solid</b> tab has Sketch and Extrude; <b>Utilities</b> has Export (STEP) and 3D Print (STL).</td></tr>
<tr><td class="k">Browser (left)</td><td>Bodies and sketches in the part, and the part's size, volume and weight.</td></tr>
<tr><td class="k">3D view (middle)</td><td>The part. View cube and Home button at the top right.</td></tr>
<tr><td class="k">Status bar</td><td>Cursor X / Y / Z and a hint for what to do next. Read it when stuck.</td></tr>
<tr><td class="k">Timeline (bottom)</td><td>Every sketch and feature, in order.</td></tr>
</table>
<h3>Moving the view</h3>
<table>
<tr><td class="k">Left drag</td><td>Orbit (spin the part)</td></tr>
<tr><td class="k">Right drag</td><td>Pan</td></tr>
<tr><td class="k">Mouse wheel</td><td>Zoom</td></tr>
<tr><td class="k">Home key</td><td>Back to the home view</td></tr>
</table>
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
<li><b>Set the height first</b> if the sketch belongs on top of something: in the palette,
set <b>Plane</b> to the Z height. Example: the demo plate is 0.5 thick, so <b>Plane 0.5</b>
draws on its top face. Leave it at 0 to draw on the bottom (XY) plane.</li>
<li>Pick a tool and click in the view:
<table>
<tr><td class="k">Line &nbsp;<b>L</b></td><td>Click start, click end. Keep clicking to chain lines. <b>Esc</b> ends the chain.</td></tr>
<tr><td class="k">Rectangle &nbsp;<b>R</b></td><td>Click one corner, then the opposite corner.</td></tr>
<tr><td class="k">Center Rect</td><td>Click the center, then a corner (ribbon button).</td></tr>
<tr><td class="k">Circle &nbsp;<b>C</b></td><td>Click the center, then a point on the circle.</td></tr>
<tr><td class="k">Polygon &nbsp;<b>P</b></td><td>Click the center, then a corner. Set the number of sides in the palette first.</td></tr>
</table>
The blue tag next to the cursor shows the size as you move (width × height, Ø, length).</li>
<li>Press <b>Enter</b> (or <b>Finish Sketch</b>). The sketch is added to the timeline as
<b>Sketch1</b>, <b>Sketch2</b>, and so on.</li>
</ol>
<h3>Snapping and accuracy</h3>
<ul>
<li><b>Grid snap</b> is on, at 0.250 in. Change <b>Snap size</b> in the palette (0.125, 0.0625, 0.010).</li>
<li>Hold <b>Shift</b> while clicking to snap four times finer.</li>
<li>Untick <b>Grid snap</b> to place points freely.</li>
</ul>
<h3>Fixing mistakes while sketching</h3>
<ul>
<li><b>Ctrl+Z</b> or <b>Undo</b> removes the last shape.</li>
<li>Click <b>×</b> next to any shape in the palette list to delete that one.</li>
<li><b>Clear</b> removes everything; <b>Cancel</b> leaves without keeping the sketch.</li>
<li><b>Esc</b> drops a half-drawn shape; press it again to put the tool down.</li>
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
<tr><td class="k">L</td><td>New sketch (in a sketch: Line)</td></tr>
<tr><td class="k">R / C / P</td><td>Rectangle / Circle / Polygon (in a sketch)</td></tr>
<tr><td class="k">Shift + click</td><td>Snap 4× finer</td></tr>
<tr><td class="k">Enter</td><td>Finish sketch / OK in Extrude</td></tr>
<tr><td class="k">Esc</td><td>Drop the current shape / end a line chain / cancel Extrude</td></tr>
<tr><td class="k">E</td><td>Extrude</td></tr>
<tr><td class="k">Ctrl+Z / Ctrl+Y</td><td>Undo / redo</td></tr>
<tr><td class="k">Ctrl+N</td><td>New part</td></tr>
<tr><td class="k">Ctrl+S / Ctrl+O</td><td>Save / open (Ctrl+Shift+S = Save As)</td></tr>
<tr><td class="k">Home</td><td>Home view</td></tr>
<tr><td class="k">Delete</td><td>Delete the sketch or body picked in the Browser</td></tr>
<tr><td class="k">F2</td><td>Rename the sketch or body picked in the Browser</td></tr>
<tr><td class="k">F1</td><td>This documentation</td></tr>
</table>
<p class="tip">Hole, Fillet, Chamfer and some other ribbon tools are not in this build yet;
clicking them says so.</p>
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
