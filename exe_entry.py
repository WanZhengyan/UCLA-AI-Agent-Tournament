"""PyInstaller entry. freeze_support must run before argparse or any prompts."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from launcher import main
    raise SystemExit(main())

