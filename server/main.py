"""Application entry point: run with `python main.py` to start the gallery."""

from gallery.app import create_app
from gallery.configuration import Settings
from gallery.server_runtime import serve


def main() -> None:
    settings = Settings.from_environment()
    application = create_app(settings)
    serve(application, settings)


if __name__ == "__main__":
    main()
