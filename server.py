#!/usr/bin/env python3
"""
MF Sculpture — Local Gallery Server
Serves static files and handles image uploads for the admin panel.
Usage: python3 server.py [port]  (default: 8200)
"""

import http.server
import json
import os
import sys
import uuid
import base64
import mimetypes
import threading
from urllib.parse import urlparse, parse_qs
from io import BytesIO

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8200
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, 'images')
GALLERY_JSON = os.path.join(BASE_DIR, 'gallery.json')
ABOUT_JSON = os.path.join(BASE_DIR, 'about.json')
HERO_JSON = os.path.join(BASE_DIR, 'hero.json')

THUMBS_DIR = os.path.join(BASE_DIR, 'images', 'thumbs')

# Ensure directories exist
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(THUMBS_DIR, exist_ok=True)

# Ensure gallery.json exists
if not os.path.exists(GALLERY_JSON):
    with open(GALLERY_JSON, 'w') as f:
        json.dump([], f)

# Ensure about.json exists
if not os.path.exists(ABOUT_JSON):
    with open(ABOUT_JSON, 'w') as f:
        json.dump({}, f)

# Ensure hero.json exists
if not os.path.exists(HERO_JSON):
    with open(HERO_JSON, 'w') as f:
        json.dump({}, f)


gallery_lock = threading.Lock()

def read_gallery():
    with open(GALLERY_JSON, 'r') as f:
        return json.load(f)


def write_gallery(data):
    with open(GALLERY_JSON, 'w') as f:
        json.dump(data, f, indent=2)


def read_about():
    with open(ABOUT_JSON, 'r') as f:
        return json.load(f)


def write_about(data):
    with open(ABOUT_JSON, 'w') as f:
        json.dump(data, f, indent=2)


def read_hero():
    with open(HERO_JSON, 'r') as f:
        return json.load(f)


def write_hero(data):
    with open(HERO_JSON, 'w') as f:
        json.dump(data, f, indent=2)


class GalleryHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/gallery':
            self._json_response(read_gallery())
        elif parsed.path == '/api/about':
            self._json_response(read_about())
        elif parsed.path == '/api/hero':
            self._json_response(read_hero())
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        if parsed.path == '/api/upload':
            self._handle_upload(body)
        elif parsed.path == '/api/regen-thumb':
            self._handle_regen_thumb(body)
        elif parsed.path == '/api/gallery':
            self._handle_save_gallery(body)
        elif parsed.path == '/api/about':
            self._handle_save_about(body)
        elif parsed.path == '/api/artist-photo':
            self._handle_artist_photo(body)
        elif parsed.path == '/api/hero':
            self._handle_save_hero(body)
        else:
            self._json_response({'error': 'Not found'}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith('/api/gallery/'):
            image_id = parsed.path.split('/')[-1]
            self._handle_delete(image_id)
        else:
            self._json_response({'error': 'Not found'}, 404)

    def _handle_upload(self, body):
        try:
            print(f"  Upload: received {len(body)} bytes")
            data = json.loads(body)
            full_data = data.get('fullData', '')      # full-resolution base64
            thumb_data = data.get('thumbData', '')     # thumbnail base64
            title = data.get('title', 'Untitled')
            material = data.get('material', 'Metal')

            # Backwards compat: if old-style single imageData sent
            if not full_data:
                full_data = data.get('imageData', '')
            if not thumb_data:
                thumb_data = full_data

            if ',' not in full_data:
                self._json_response({'error': 'Invalid image data'}, 400)
                return

            header, b64_full = full_data.split(',', 1)
            if 'png' in header:
                ext = '.png'
            elif 'webp' in header:
                ext = '.webp'
            else:
                ext = '.jpg'

            # Generate unique filename
            filename = f"{uuid.uuid4().hex[:12]}{ext}"

            # Save full-resolution image
            full_bytes = base64.b64decode(b64_full)
            with open(os.path.join(IMAGES_DIR, filename), 'wb') as f:
                f.write(full_bytes)

            # Save thumbnail
            if ',' in thumb_data:
                _, b64_thumb = thumb_data.split(',', 1)
                thumb_bytes = base64.b64decode(b64_thumb)
            else:
                thumb_bytes = full_bytes

            with open(os.path.join(THUMBS_DIR, filename), 'wb') as f:
                f.write(thumb_bytes)

            # Add to gallery.json (thread-safe)
            with gallery_lock:
                gallery = read_gallery()
                new_item = {
                    'id': f"img_{uuid.uuid4().hex[:10]}",
                    'title': title,
                    'material': material,
                    'filename': filename,
                    'order': len(gallery)
                }
                gallery.append(new_item)
                write_gallery(gallery)

            print(f"  Upload: saved {filename} ({len(full_bytes)} bytes full, {len(thumb_bytes)} bytes thumb)")
            self._json_response(new_item, 201)

        except Exception as e:
            print(f"  Upload ERROR: {e}")
            self._json_response({'error': str(e)}, 500)

    def _handle_save_gallery(self, body):
        try:
            data = json.loads(body)
            with gallery_lock:
                write_gallery(data)
            self._json_response({'status': 'ok'})
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _handle_regen_thumb(self, body):
        """Replace a single thumbnail from client-supplied base64 data."""
        try:
            data = json.loads(body)
            filename = data.get('filename', '')
            thumb_data = data.get('thumbData', '')

            if not filename or ',' not in thumb_data:
                self._json_response({'error': 'Missing filename or thumbData'}, 400)
                return

            # Security: prevent path traversal
            filename = os.path.basename(filename)
            _, b64 = thumb_data.split(',', 1)
            thumb_bytes = base64.b64decode(b64)

            with open(os.path.join(THUMBS_DIR, filename), 'wb') as f:
                f.write(thumb_bytes)

            self._json_response({'status': 'ok', 'filename': filename})

        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _handle_save_hero(self, body):
        try:
            data = json.loads(body)
            write_hero(data)
            self._json_response({'status': 'ok'})
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _handle_save_about(self, body):
        try:
            data = json.loads(body)
            # Preserve artistPhoto if not in this save
            existing = read_about()
            if existing.get('artistPhoto') and 'artistPhoto' not in data:
                data['artistPhoto'] = existing['artistPhoto']
            write_about(data)
            self._json_response({'status': 'ok'})
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _handle_artist_photo(self, body):
        try:
            data = json.loads(body)
            image_data = data.get('imageData', '')
            if ',' not in image_data:
                self._json_response({'error': 'Invalid image data'}, 400)
                return

            _, b64 = image_data.split(',', 1)
            img_bytes = base64.b64decode(b64)
            filename = 'artist-photo.jpg'

            with open(os.path.join(IMAGES_DIR, filename), 'wb') as f:
                f.write(img_bytes)

            # Store reference in about.json
            about = read_about()
            about['artistPhoto'] = filename
            write_about(about)

            print(f"  Artist photo saved: {filename} ({len(img_bytes)} bytes)")
            self._json_response({'status': 'ok', 'filename': filename})

        except Exception as e:
            print(f"  Artist photo ERROR: {e}")
            self._json_response({'error': str(e)}, 500)

    def _handle_delete(self, image_id):
        try:
            with gallery_lock:
                gallery = read_gallery()
                item = next((i for i in gallery if i['id'] == image_id), None)

                if not item:
                    self._json_response({'error': 'Not found'}, 404)
                    return

                # Delete the image file + thumbnail
                filepath = os.path.join(IMAGES_DIR, item['filename'])
                thumbpath = os.path.join(THUMBS_DIR, item['filename'])
                if os.path.exists(filepath):
                    os.remove(filepath)
                if os.path.exists(thumbpath):
                    os.remove(thumbpath)

                # Remove from gallery and reorder
                gallery = [i for i in gallery if i['id'] != image_id]
                for idx, g in enumerate(gallery):
                    g['order'] = idx
                write_gallery(gallery)

            self._json_response({'status': 'deleted'})

        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        # Cleaner logging
        msg = format % args
        if '/api/' in msg:
            print(f"  API: {msg}")
        elif not any(ext in msg for ext in ['.js', '.css', '.ico', '.map']):
            print(f"  {msg}")


if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════╗
║   MF Sculpture — Gallery Server          ║
╠══════════════════════════════════════════╣
║                                          ║
║   Site:   http://localhost:{PORT}          ║
║   Admin:  http://localhost:{PORT}/admin.html║
║                                          ║
║   Press Ctrl+C to stop                   ║
╚══════════════════════════════════════════╝
""")
    # Use ThreadingHTTPServer so large uploads don't block other requests
    with http.server.ThreadingHTTPServer(('', PORT), GalleryHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
