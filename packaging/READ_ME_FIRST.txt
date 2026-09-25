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
  L            start a sketch (Line, Rectangle, Center Rect, Circle, Polygon; Shift = fine snap)
  Enter        finish the sketch
  Edit sketch  right-click a sketch in the timeline (or double-click it in the Browser)
  Hide sketch  click the dot next to it in the Browser, or right-click -> Hide Sketch
  E            extrude: click profiles in the view, set Distance / Direction / Operation, OK
  Esc          cancel / end a line chain
  Ctrl+Z / Y   undo / redo
  Ctrl+S / O   save / open (.gcad files)
  Home         home view
  Mouse        left drag = orbit, right drag = pan, wheel = zoom
  Timeline     click a feature to roll back; right-click to delete
  Utilities    Export = STEP, 3D Print = STL

IF IT WON'T START
  An error message names a crash log, usually:
      %LOCALAPPDATA%\G00CAM\crash.log
  Send that file (or a screenshot of the message).

  Health check without opening the window (writes a short report):
      "G00 CAM.exe" --selftest "%USERPROFILE%\Desktop\g00cam_check.txt"
