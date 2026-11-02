import base64
import concurrent.futures
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')

class RelayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_data = server.DATA
        server.DATA = Path(self.temp.name)
        server.initialize()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        server.DATA = self.previous_data
        self.temp.cleanup()

    def call(self, path, data=None, content_type='application/json'):
        request = urllib.request.Request(self.url + path, data=data, headers={'Content-Type': content_type})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def upload(self, count=1, image=PNG):
        body = b''.join(b'--test-boundary\r\nContent-Disposition: form-data; name="images"; filename="test.png"\r\nContent-Type: image/png\r\n\r\n' + image + b'\r\n' for _ in range(count)) + b'--test-boundary--\r\n'
        return self.call('/api/requests', body, 'multipart/form-data; boundary=test-boundary')

    def test_concurrent_requests_and_reply_isolation(self):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = list(pool.map(self.upload, [1, 2]))
        self.assertTrue(all(status == 201 for status, _ in results))
        first, second = [json.loads(body) for _, body in results]
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(second['images']), 2)
        self.assertEqual(self.call(first['images'][0]['url'])[1], PNG)
        path = '/api/requests/' + first['id'] + '/reply'
        self.assertEqual(self.call(path)[0], 202)
        reply = 'Hello\n世界 "quoted"'
        self.assertEqual(self.call(path, json.dumps({'text': reply}).encode())[0], 200)
        self.assertEqual(self.call(path), (200, reply.encode()))
        self.assertEqual(self.call(path, b'{"text":"again"}')[0], 409)
        self.assertEqual(self.call('/api/requests/' + second['id'] + '/reply')[0], 202)
        server.initialize()
        self.assertEqual(self.call(path)[1], reply.encode())

    def test_invalid_input(self):
        self.assertEqual(self.upload(image=b'not an image')[0], 415)
        self.assertEqual(self.upload(count=0)[0], 400)
        self.assertEqual(self.call('/api/requests/missing/reply', b'{"text":"hi"}')[0], 404)
        self.assertEqual(self.call('/api/requests/missing/reply', b'{"text":" "}')[0], 400)
        self.assertEqual(self.call('/')[0], 200)

    @unittest.skipUnless((server.ROOT / 'relay-client').exists(), 'Build relay-client to test C++ exchange')
    def test_cpp_client(self):
        image = Path(self.temp.name) / 'input.png'
        image.write_bytes(PNG)
        process = subprocess.Popen([str(server.ROOT / 'relay-client'), self.url, str(image), str(image)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                items = json.loads(self.call('/api/requests')[1])
                if items:
                    break
                time.sleep(.05)
            self.assertTrue(items)
            self.assertEqual(len(items[0]['images']), 2)
            self.call('/api/requests/' + items[0]['id'] + '/reply', json.dumps({'text': 'exact reply\n世界'}).encode())
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err.decode())
            self.assertEqual(out.decode(), 'exact reply\n世界\n')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

if __name__ == '__main__':
    unittest.main()
