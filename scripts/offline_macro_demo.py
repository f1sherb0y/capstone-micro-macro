"""Launch the native offline host with a separate, writable demo database."""
from pathlib import Path
import importlib
import runpy
import sys

from integration.bootstrap import enable_gba_imports


def main():
    database = Path(sys.argv[1]).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    enable_gba_imports()
    storage = importlib.import_module('gba_construction_sim.backend.storage.agent_database')
    storage.agent_database = storage.AgentDatabase(db_path=database)
    sys.argv = ['integration.run', *sys.argv[2:]]
    runpy.run_module('integration.run', run_name='__main__')


if __name__ == '__main__':
    main()
