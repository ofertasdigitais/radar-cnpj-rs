"""Free regional OSM index; independent of the application/customer database.

Only fixed Geofabrik HTTPS resources are downloaded. Never interpret tags as code,
guess a CNPJ identity, or assign a municipality from its postal text alone.
"""
import hashlib
import gc
import subprocess
import sys
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DIRECTORY = Path(os.environ.get('RADAR_DATA_DIR', str(ROOT / 'data'))) / 'osm-local'
SOURCE = 'https://download.geofabrik.de/south-america/brazil/sul-latest.osm.pbf'
MAX_BYTES = 1024 * 1024 * 1024
MAX_SECONDS = 1800
SCHEMA = 1


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def city_key(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value))
                           if not unicodedata.combining(c)).casefold().split())


def _atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def readonly(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        yield db


def _catalog(directory=DIRECTORY):
    directory = Path(directory)
    manifest = json.loads((directory / 'CURRENT.json').read_text(encoding='utf-8'))
    name = manifest.get('file', '')
    if manifest.get('schema') != SCHEMA or not re.fullmatch(r'index-[a-f0-9]{32}\.sqlite', name):
        raise ValueError('Índice local incompatível; prepare uma nova versão.')
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Índice local ausente.')
    return path, manifest


def status(directory=DIRECTORY):
    result = {'ready': False, 'source': 'Geofabrik / OpenStreetMap', 'free': True,
              'message': 'Índice local ainda não preparado. Execute a preparação local do índice.',
              'cities': [], 'count': 0, 'version': '', 'built_at': '', 'stale': False}
    try:
        path, manifest = _catalog(directory)
        with readonly(path) as db:
            meta = json.loads(db.execute('SELECT value FROM metadata WHERE key=\'manifest\'').fetchone()[0])
            if meta['schema'] != SCHEMA:
                raise ValueError('Versão incompatível')
            result.update(ready=True, count=meta['count'], version=manifest['file'],
                          built_at=meta['built_at'], source_timestamp=meta.get('source_timestamp', ''),
                          cities=[dict(r) for r in db.execute('SELECT name,ibge FROM cities ORDER BY name')])
            age = datetime.now(timezone.utc) - datetime.fromisoformat(meta['built_at'])
            result['stale'] = age.total_seconds() > 7 * 86400
            result['message'] = ('Índice com mais de 7 dias; atualização recomendada.' if result['stale'] else
                                 'Índice local pronto; consultas não dependem da API Overpass.')
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        pass
    try:
        result['update'] = json.loads((Path(directory) / 'UPDATE.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        result['update'] = {'status': 'aguardando'}
    return result


def fetch(city, category, cursors=None, *, directory=DIRECTORY):
    from discovery import CATEGORIES
    if category not in CATEGORIES:
        raise ValueError('Categoria não suportada')
    path, _ = _catalog(directory)
    cursors = cursors or {}
    with readonly(path) as db:
        municipal = db.execute('SELECT ibge FROM cities WHERE city_key=?', (city_key(city),)).fetchone()
        if not municipal:
            raise ValueError('Município não encontrado nos limites OSM do RS. Confira o município disponível na lista.')
        # All object kinds share a stable ordering with the manager's 50+1 cursor.
        rows = db.execute('''SELECT kind,osm_id,tags_json FROM places WHERE city_ibge=? AND category=?
            AND ((kind='node' AND osm_id>?) OR (kind='way' AND osm_id>?) OR
                 (kind='relation' AND osm_id>?))
            ORDER BY CASE kind WHEN 'node' THEN 0 WHEN 'way' THEN 1 ELSE 2 END,osm_id LIMIT 51''',
            (municipal['ibge'], category, *[max(0, int(cursors.get(k, 0))) for k in ('node', 'way', 'relation')]))
        return [dict(type=r['kind'], id=r['osm_id'], tags=json.loads(r['tags_json'])) for r in rows]


class FixedSourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != 'https' or url.hostname != 'download.geofabrik.de' or url.username or url.password:
            raise ValueError('Redirecionamento externo não permitido.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(destination, *, opener=None, max_bytes=MAX_BYTES, deadline_seconds=MAX_SECONDS):
    """An incomplete transfer is never handed to the importer."""
    opener = opener or build_opener(FixedSourceRedirect()).open
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + deadline_seconds
    request = Request(SOURCE, headers={'User-Agent': 'RadarCNPJ/1.0 local-OSM-weekly-index'})
    try:
        with opener(request, timeout=45) as response, Path(destination).open('xb') as output:
            length = int(response.headers.get('Content-Length') or 0)
            if length > max_bytes:
                raise ValueError('Arquivo regional acima do limite de 1 GB.')
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('Tempo de download excedido.')
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError('Download acima do limite seguro.')
                output.write(chunk)
                digest.update(chunk)
            if not total or (length and total != length):
                raise ValueError('Download regional incompleto.')
            output.flush()
            os.fsync(output.fileno())
        return {'source': SOURCE, 'bytes': total, 'sha256': digest.hexdigest()}
    except Exception:
        Path(destination).unlink(missing_ok=True)
        raise


@contextmanager
def update_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.update.lock'
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('Já existe atualização ou uma atualização foi interrompida. Veja CAPTACAO-GRATUITA.md.') from None
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def build_index(source, destination, categories, *, source_meta=None, minimum_cities=1):
    # Isolate native PBF memory/index handles. Child exit releases mmap handles
    # reliably on Windows before the parent removes its generated staging files.
    payload = dict(source=str(source), destination=str(destination), categories=categories,
                   source_meta=source_meta, minimum_cities=minimum_cities)
    environment = {k: v for k, v in os.environ.items() if k.upper() in
                   {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT'}}
    environment['PYTHONUTF8'] = '1'
    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--build-worker'],
                             input=json.dumps(payload), capture_output=True, text=True,
                             encoding='utf-8', env=environment, timeout=MAX_SECONDS,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        raise ValueError('Processamento OSM recusado: ' + process.stderr.strip()[-600:])
    return json.loads(process.stdout)


def _build_index(source, destination, categories, *, source_meta=None, minimum_cities=1):
    """Stream PBF/XML, assemble RS municipal polygons, spatially attribute POIs.

    source/destination belong to the staging directory, not the Radar database.
    The disk-backed location index prevents keeping all regional nodes in RAM.
    """
    import osmium
    from shapely import from_wkb, Point, STRtree
    source, destination = Path(source), Path(destination)
    reader = osmium.io.Reader(str(source))
    try:
        source_timestamp = reader.header().get('osmosis_replication_timestamp') or ''
    finally:
        reader.close()
    geometries, municipalities = [], []
    stats = {'candidates': 0, 'geometry_skipped': 0, 'unassigned': 0, 'ambiguous': 0}
    factory = osmium.geom.WKBFactory()
    wanted = {key for _, terms in categories.values() for key, _ in terms}
    kept = {'name', 'brand', 'phone', 'contact:phone', 'website', 'contact:website', 'email',
            'contact:email', 'addr:street', 'addr:housenumber', 'addr:suburb', 'addr:city',
            'addr:state', 'contact:facebook', 'contact:instagram'} | wanted

    with closing(sqlite3.connect(destination)) as db:
        db.executescript('''PRAGMA journal_mode=DELETE;
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE cities(ibge TEXT PRIMARY KEY,name TEXT NOT NULL,city_key TEXT UNIQUE NOT NULL);
            CREATE TABLE candidates(kind TEXT,osm_id INTEGER,tags_json TEXT,x REAL,y REAL,
                PRIMARY KEY(kind,osm_id));
            CREATE TABLE places(kind TEXT,osm_id INTEGER,city_ibge TEXT,category TEXT,tags_json TEXT,
                PRIMARY KEY(kind,osm_id,category));
            CREATE INDEX place_lookup ON places(city_ibge,category,kind,osm_id);''')

        def relevant(tags):
            return bool(tags.get('name') or tags.get('brand')) and any(tags.get(k) == v for _, terms in categories.values() for k, v in terms)

        def add(kind, identifier, tags, point):
            if point.is_empty or not (-58 <= point.x <= -48 and -34 <= point.y <= -26):
                return
            # Text is bounded before storage; HTML is escaped by the existing UI.
            tagdict = {k: str(tags.get(k))[:500] for k in kept if tags.get(k)}
            db.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?)',
                       (kind, identifier, json.dumps(tagdict, ensure_ascii=False), point.x, point.y))
            stats['candidates'] += 1

        class Handler(osmium.SimpleHandler):
            def node(self, node):
                if relevant(node.tags):
                    if node.location.valid():
                        add('node', node.id, node.tags, Point(node.location.lon, node.location.lat))
                    else:
                        stats['geometry_skipped'] += 1

            def way(self, way):
                if not relevant(way.tags):
                    return
                try:
                    line = from_wkb(factory.create_linestring(way))
                    add('way', way.id, way.tags, line.interpolate(0.5, normalized=True))
                except (RuntimeError, ValueError):
                    stats['geometry_skipped'] += 1

            def area(self, area):
                tags = area.tags
                # Current Brazilian boundaries primarily use IBGE:GEOCODIGO;
                # older extracts can still carry ref:IBGE.
                ibge = tags.get('IBGE:GEOCODIGO') or tags.get('ref:IBGE', '')
                municipal = tags.get('admin_level') == '8' and tags.get('boundary') == 'administrative' and re.fullmatch(r'43\d{5}', ibge)
                poi = relevant(tags)
                if not municipal and not poi:
                    return
                try:
                    geom = from_wkb(factory.create_multipolygon(area))
                    if not geom.is_valid or geom.is_empty:
                        stats['geometry_skipped'] += 1
                        return
                    if municipal and tags.get('name'):
                        municipalities.append((ibge, tags.get('name')[:100]))
                        geometries.append(geom)
                    if poi:
                        add('way' if area.from_way() else 'relation', area.orig_id(), tags, geom.representative_point())
                except (RuntimeError, ValueError):
                    stats['geometry_skipped'] += 1

        location_index = destination.with_suffix('.locations')
        try:
            # Locations/area assembly still see every required node/member.
            # Native filtering avoids millions of Python callbacks for roads,
            # bare geometry nodes and other unrelated regional map features.
            Handler().apply_file(str(source), locations=True, idx='sparse_file_array,' + str(location_index),
                                 filters=[osmium.filter.KeyFilter(*sorted(wanted | {'boundary'}))])
        finally:
            # Pyosmium can retain callback cycles until GC, holding mmap handles
            # open on Windows even after apply_file returns.
            gc.collect()
            # Native sparse_file_array can hold its file until process exit.
            # Parent cleans it after the worker has terminated.
            try:
                location_index.unlink(missing_ok=True)
            except PermissionError:
                pass
        if len(set(code for code, _ in municipalities)) < minimum_cities:
            raise ValueError(f'Limites municipais do RS insuficientes: {len(set(code for code, _ in municipalities))}/{minimum_cities}; índice anterior preservado. Geometrias recusadas: {stats["geometry_skipped"]}.')
        for ibge, name in municipalities:
            db.execute('INSERT OR IGNORE INTO cities VALUES(?,?,?)', (ibge, name, city_key(name)))
        tree = STRtree(geometries)
        count = 0
        # No guess from addr:city: only one unambiguous polygon is accepted.
        for row in db.execute('SELECT kind,osm_id,tags_json,x,y FROM candidates'):
            point = Point(row[3], row[4])
            matches = {municipalities[int(i)][0] for i in tree.query(point)
                       if geometries[int(i)].covers(point)}
            if len(matches) != 1:
                stats['ambiguous' if matches else 'unassigned'] += 1
                continue
            ibge = next(iter(matches))
            tags = json.loads(row[2])
            for category, (_, terms) in categories.items():
                if any(tags.get(k) == v for k, v in terms):
                    db.execute('INSERT OR REPLACE INTO places VALUES(?,?,?,?,?)', (*row[:2], ibge, category, row[2]))
                    count += 1
        db.execute('DROP TABLE candidates')
        meta = {**(source_meta or {}), 'schema': SCHEMA, 'built_at': timestamp(),
                'source_timestamp': source_timestamp,
                'count': count, 'cities': len(set(code for code, _ in municipalities)),
                'stats': stats, 'attribution': '© OpenStreetMap contributors · ODbL 1.0'}
        db.execute('INSERT INTO metadata VALUES(?,?)', ('manifest', json.dumps(meta, ensure_ascii=False)))
        db.commit()
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Integridade do índice reprovada.')
        return meta


def update(*, directory=DIRECTORY, source_file=None, minimum_cities=490, progress=None):
    """Retain last good generation on any failure. No access to customer tables."""
    from discovery import CATEGORIES
    directory = Path(directory)
    with update_lock(directory):
        stage = directory / ('staging-' + uuid.uuid4().hex)
        stage.mkdir()
        source = Path(source_file) if source_file else stage / 'sul.osm.pbf'
        def report(state, message):
            _atomic_json(directory / 'UPDATE.json', {'status': state, 'message': message, 'at': timestamp()})
            if progress:
                progress(message)
        try:
            if shutil.disk_usage(directory).free < 4 * 1024**3:
                raise ValueError('Reserve ao menos 4 GB livres para a preparação regional.')
            if source_file:
                meta = {'source': 'arquivo-local-de-teste', 'bytes': source.stat().st_size}
            else:
                report('baixando', 'Baixando Região Sul da Geofabrik; nenhum serviço pago.')
                meta = download(source)
            report('indexando', 'Processando municípios RS e estabelecimentos; índice anterior continua disponível.')
            index = stage / 'building.sqlite'
            meta = build_index(source, index, CATEGORIES, source_meta=meta, minimum_cities=minimum_cities)
            if not meta['count']:
                raise ValueError('Índice sem estabelecimentos; publicação cancelada.')
            filename = 'index-' + uuid.uuid4().hex + '.sqlite'
            published = directory / filename
            os.replace(index, published)
            # A pointer switch, rather than replacing an open SQLite file, works on Windows.
            _atomic_json(directory / 'CURRENT.json', {'schema': SCHEMA, 'file': filename})
            report('pronto', f"Índice pronto: {meta['count']} registros por categoria / {meta['cities']} municípios RS.")
            return meta
        except Exception:
            report('falhou', 'Atualização não concluída. Índice anterior preservado. Consulte o comando local para detalhes.')
            raise
        finally:
            # Strictly generated staging data; never delete the index or original source.
            if stage.parent.resolve() == directory.resolve() and re.fullmatch(r'staging-[a-f0-9]{32}', stage.name):
                shutil.rmtree(stage)


_scheduler_started = False


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    def loop():
        import admin_panel
        # Once a day at most; an update failure must not cause a download loop.
        last_attempt = float('-inf')
        while True:
            try:
                state = status()
                previous = state['update'].get('at')
                recent = previous and (datetime.now(timezone.utc) - datetime.fromisoformat(previous)).total_seconds() < 86400
                if admin_panel.get('osm_local_auto_update') and not recent and time.monotonic() - last_attempt >= 86400 and (not state['ready'] or state['stale']):
                    last_attempt = time.monotonic()
                    update()
            except Exception:
                pass
            time.sleep(60)
    threading.Thread(target=loop, daemon=True, name='radar-osm-local-weekly').start()


if __name__ == '__main__' and sys.argv[1:] == ['--build-worker']:
    try:
        payload = json.loads(sys.stdin.read(50000))
        result = _build_index(**payload)
        sys.stdout.write(json.dumps(result, ensure_ascii=True))
    except Exception as error:
        sys.stderr.write(f'{type(error).__name__}: {error}')
        raise SystemExit(1)
