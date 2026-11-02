#!/usr/bin/env python3
"""Image-to-text relay. Python standard library only."""
import argparse
import email.policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import time
import uuid

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
MAX_UPLOAD = 50 * 1024 * 1024


def db():
    con = sqlite3.connect(DATA / 'relay.sqlite')
    con.row_factory = sqlite3.Row
    return con


def initialize():
    DATA.mkdir(exist_ok=True)
    (DATA / 'images').mkdir(exist_ok=True)
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, created REAL, reply TEXT, images TEXT)')


def record(row):
    return {'id': row['id'], 'created': row['created'], 'reply': row['reply'],
            'status': 'pending' if row['reply'] is None else 'replied', 'images': json.loads(row['images'])}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/requests':
            with db() as con:
                rows = con.execute('SELECT * FROM requests ORDER BY created DESC').fetchall()
            return self.send(200, [record(row) for row in rows])
        if path.startswith('/api/requests/'):
            request_id = path.removeprefix('/api/requests/')
            plain_reply = request_id.endswith('/reply')
            if plain_reply:
                request_id = request_id[:-len('/reply')]
            with db() as con:
                row = con.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if row and plain_reply:
                return self.send(202, b'') if row['reply'] is None else self.send(200, row['reply'].encode(), 'text/plain; charset=utf-8')
            return self.send(200, record(row)) if row else self.send(404, {'error': 'Request not found'})
        if path.startswith('/images/'):
            name = path.removeprefix('/images/')
            if '/' in name or '\\' in name or name.startswith('.'):
                return self.send(404, {'error': 'Not found'})
            file = DATA / 'images' / name
            if file.is_file():
                mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}[file.suffix[1:]]
                return self.send(200, file.read_bytes(), mime)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in assets:
            name, mime = assets[path]
            return self.send(200, (ROOT / 'public' / name).read_bytes(), mime)
        self.send(404, {'error': 'Not found'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send(400, {'error': 'Invalid Content-Length'})
        if length <= 0 or length > MAX_UPLOAD:
            self.close_connection = True
            return self.send(413, {'error': 'Body must be between 1 byte and 50 MiB'})
        body = self.rfile.read(length)
        if self.path == '/api/requests':
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                return self.send(415, {'error': 'Use multipart/form-data with image fields named images'})
            message = BytesParser(policy=email.policy.default).parsebytes(
                ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
            files = []
            for part in message.iter_parts():
                if part.get_param('name', header='content-disposition') != 'images':
                    continue
                payload = part.get_payload(decode=True) or b''
                if payload.startswith(b'\x89PNG\r\n\x1a\n'):
                    ext = 'png'
                elif payload.startswith(b'\xff\xd8\xff'):
                    ext = 'jpg'
                elif payload.startswith((b'GIF87a', b'GIF89a')):
                    ext = 'gif'
                elif payload.startswith(b'RIFF') and payload[8:12] == b'WEBP':
                    ext = 'webp'
                else:
                    return self.send(415, {'error': 'Only PNG, JPEG, GIF and WebP images are supported'})
                files.append((part.get_filename() or 'image.' + ext, payload, ext))
            if not files or len(files) > 20:
                return self.send(400, {'error': 'Supply between 1 and 20 images'})
            request_id = uuid.uuid4().hex
            images = []
            for name, payload, ext in files:
                filename = uuid.uuid4().hex + '.' + ext
                (DATA / 'images' / filename).write_bytes(payload)
                images.append({'name': name, 'url': '/images/' + filename})
            with db() as con:
                con.execute('INSERT INTO requests VALUES (?, ?, NULL, ?)', (request_id, time.time(), json.dumps(images)))
                row = con.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            return self.send(201, record(row))
        if self.path.startswith('/api/requests/') and self.path.endswith('/reply'):
            request_id = self.path[len('/api/requests/'):-len('/reply')]
            try:
                reply = json.loads(body)['text']
                if not isinstance(reply, str) or not reply.strip() or len(reply) > 100000:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                return self.send(400, {'error': 'text must contain 1–100,000 characters'})
            with db() as con:
                changed = con.execute('UPDATE requests SET reply=? WHERE id=? AND reply IS NULL', (reply, request_id)).rowcount
                exists = con.execute('SELECT 1 FROM requests WHERE id=?', (request_id,)).fetchone()
            return self.send(200, {'ok': True}) if changed else self.send(409 if exists else 404, {'error': 'Already replied' if exists else 'Request not found'})
        self.send(404, {'error': 'Not found'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    initialize()
    print(f'Image relay running at http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
