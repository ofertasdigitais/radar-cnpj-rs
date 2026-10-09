"""Explicit preparation in the local application; never imports app.py."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import local_osm

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepara somente o índice público do Radar.')
    parser.add_argument('--source', type=Path, help='Reutiliza um arquivo .osm.pbf já baixado, sem novo download.')
    args = parser.parse_args()
    try:
        metadata = local_osm.update(source_file=args.source, progress=lambda message: print(message, flush=True))
        print('Preparação concluída. Somente o índice público local foi atualizado.', flush=True)
    except Exception as error:
        print(f'Preparação interrompida: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)
