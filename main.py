"""Money Maker 911 entry point. No args = desktop app. `main.py render|batch|thumb|cutout ...` = command line."""
import sys


def run():
    if len(sys.argv) > 1 and sys.argv[1] in ("render", "batch", "thumb", "cutout"):
        from mm911.cli import main
        main(sys.argv[1:])
    else:
        from mm911.gui.app import main
        main()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    run()
