G00 CAM  -  Rev 1 (test build)
==============================

RUN IT
  Double-click "G00 CAM.exe".
  Keep the "_internal" folder next to it. The exe needs everything in there.

  First launch: Windows may show "Windows protected your PC" because this test build isn't
  code-signed. Click "More info", then "Run anyway". It only asks once.

HOW TO USE IT
  Help (top right) -> Documentation, or press F1: step by step for sketching, editing a
  sketch, hiding a sketch, and making a solid (extrude).

CONTROLS
  Ctrl+N       new, empty part (FILE menu, top left: New / Open / Save / Save As / Export)
  L            start a sketch (Line, Rectangle, Center Rect, Circle, Polygon; Shift = fine snap)
  Enter        finish the sketch
  Edit sketch  right-click a sketch in the timeline (or double-click it in the Browser)
  Hide sketch  click the dot next to it in the Browser, or right-click -> Hide Sketch
  Rename       right-click a sketch or body in the Browser -> Rename (or F2)
  Delete       click a sketch or body in the Browser, press Delete (Ctrl+Z brings it back)
  E            extrude: click profiles in the view, set Distance / Direction / Operation, OK
  Esc          cancel / end a line chain
  Ctrl+Z / Y   undo / redo
  Ctrl+S / O   save / open (.gcad files)
  Home         home view
  Mouse        left drag = orbit, right drag = pan, wheel = zoom
  Timeline     click a feature to roll back; right-click to delete
  Utilities    Export = STEP, 3D Print = STL

IF IT WON'T START
  A G00 logo appears while it loads. The first start on a new computer can take up to a
  minute (antivirus scans the program once). Click once and wait.

  Logs are in %LOCALAPPDATA%\G00CAM  (paste that into Win+R):
      startup.log        how far the last start got
      crash.log          Python errors (an error box names it)
      native_crash.log   hard crashes (graphics driver / 3D view)
      vtk.log            3D view / OpenGL messages
  If a start dies silently, the next start shows what these caught. Send that (or the files).

  Health check (includes the OpenGL version; the 3D view needs 3.2 or newer):
      "G00 CAM.exe" --selftest "%USERPROFILE%\Desktop\g00cam_check.txt"
