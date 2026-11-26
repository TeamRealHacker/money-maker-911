"""Money Maker 911 entry point. No args = desktop app, otherwise a command line command
(`main.py render|batch|thumb|cutout|sounds|dedupe|colab|publish|update|preflight ...`)."""
import sys

# every command the CLI knows; anything else (or nothing) opens the desktop app
CLI_COMMANDS = ("render", "batch", "thumb", "cutout", "sounds", "dedupe", "colab", "publish",
                "update", "preflight")


def run():
    if len(sys.argv) > 1 and sys.argv[1] in CLI_COMMANDS:
        from mm911.cli import main
        main(sys.argv[1:])
    else:
        from mm911.gui.app import main
        main()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    run()
