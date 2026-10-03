"""Entry point for the frozen G-SEND CADCAM app (PyInstaller).

The app's own code is NOT frozen into the exe: it lives as plain files in <exe folder>/app/
(see packaging/update_app.py), so code/font/logo changes never need a rebuild or re-signing.
"""
import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, "app"))
    from gsend_cad.ui.app import main
    main()
