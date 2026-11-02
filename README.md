# Image Relay

A self-hosted image upload and text reply server, with a browser interface and a C++ client. Requires Python 3.10+; the client requires C++17 and libcurl development headers.

## Run

```sh
python3 server.py
```

Open **http://localhost:8080** in a browser. In another terminal:

```sh
g++ -std=c++17 -O2 client.cpp -o relay-client $(pkg-config --cflags --libs libcurl)
./relay-client http://localhost:8080 first.png second.jpg
```

The client uploads all images as one request, then waits for the browser user to reply. Open the request on the webpage, copy or save its images, paste text, and press **Send reply**. The C++ function returns that exact UTF-8 text and the example prints it to stdout. Progress and errors go to stderr. Each invocation creates an independent request; simultaneous clients cannot consume each other's replies. Waiting expires after one hour by default.

Copy image requires a browser with image clipboard support and a secure context (`localhost` or HTTPS). It copies a PNG rendering of the image; Save downloads the original file. On browsers without clipboard support, open the image to copy it manually or use Save.

## Another computer

```sh
python3 server.py --host 0.0.0.0 --port 8080
./relay-client http://SERVER_LAN_IP:8080 image.png
```

Open that same server address in the browser. This version has no authentication: use it on a trusted local network. Before exposing it to the internet, add HTTPS and authentication to both the UI and API. Requests, replies and uploaded images persist under `data/`; no automatic deletion is implemented.

## HTTP API

- `POST /api/requests`: multipart form, one or more `images` file fields. Returns HTTP 201 and a JSON request containing `id`, `created`, `images`, `status`, and `reply`.
- `GET /api/requests`: lists requests, newest first.
- `GET /api/requests/{id}`: request details; `reply` is null until answered.
- `GET /api/requests/{id}/reply`: HTTP 202 while waiting; HTTP 200 with plain UTF-8 text when answered.
- `POST /api/requests/{id}/reply`: JSON `{"text":"your reply"}`. First reply wins; subsequent submissions return 409.

Uploads accept 1–20 PNG, JPEG, GIF or WebP images with a total multipart body limit of 50 MiB. Replies accept 1–100,000 characters with non-whitespace content. Image types are checked by file signatures, not fully decoded by the server.

`relay_images` in `client.cpp` can be used in an existing app; initialize libcurl once in your application before calling it. It blocks its calling thread while polling, so call it from a worker thread if your app has a UI.

## Verify

```sh
python3 -m unittest discover -s tests -v
```
