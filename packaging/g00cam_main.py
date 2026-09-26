"""Entry point for the frozen G00 CAM app (PyInstaller)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from gsend_cad.ui.app import main
    main()
