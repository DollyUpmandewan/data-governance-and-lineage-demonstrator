"""Configuration from environment; production secrets are never checked in."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from .purview_config import PurviewConfig

@dataclass
class Settings:
    database_url: str
    data_dir: Path
    secure_cookies: bool = False
    origin: str = 'http://127.0.0.1:8000'
    scan_interval: int = 300
    auto_migrate: bool = True
    purview: PurviewConfig = field(default_factory=PurviewConfig)

    @classmethod
    def from_env(cls):
        state = Path(os.getenv('STATE_DIR','runtime')).resolve()
        state.mkdir(parents=True,exist_ok=True)
        return cls(os.getenv('DATABASE_URL',f'sqlite:///{state / "catalogue.db"}'),Path(os.getenv('DATA_DIR',str(state/'sources'))).resolve(),os.getenv('COOKIE_SECURE','false').lower()=='true',os.getenv('APP_ORIGIN','http://127.0.0.1:8000').rstrip('/'),max(0,int(os.getenv('SCAN_INTERVAL_SECONDS','300'))),os.getenv('AUTO_MIGRATE','true').lower()=='true',PurviewConfig.from_env())
