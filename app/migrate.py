"""Apply migrations against the configured metadata database."""
from pathlib import Path
from alembic.config import Config
from alembic import command
from .config import Settings

def main():
    cfg = Config(str(Path(__file__).resolve().parent.parent / 'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url', Settings.from_env().database_url.replace('%', '%%'))
    command.upgrade(cfg, 'head')

if __name__ == '__main__':
    main()
