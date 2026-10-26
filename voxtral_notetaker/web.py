"""
Setup and status page, made for a phone: http://<device>:8080

- Big start/stop button and the list of meetings with their memos
- Settings (API key, email, language, Wi-Fi) protected by a PIN chosen on first visit
"""

import os
import hmac
import time
import json
import logging
import threading
from html import escape
from urllib.parse import parse_qs, quote
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional

from .config import NotetakerConfig
from .jobs import DONE, FAILED, PENDING, PROCESSING, RECORDING

log = logging.getLogger(__name__)

MAX_FORM_BYTES = 64 * 1024
LANGUAGES = [('auto', 'Automatic'), ('de-CH', 'Swiss German'), ('de', 'German'), ('en', 'English')]
STATUS_LABELS = {
    RECORDING: ('Recording', 'rec'),
    PENDING: ('Waiting', 'wait'),
    PROCESSING: ('Creating memo…', 'wait'),
    DONE: ('Done', 'ok'),
    FAILED: ('Needs attention', 'bad'),
}

STYLE = """
:root { --bg:#f6f6f4; --card:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#e3e3de;
        --accent:#2d6cdf; --rec:#d93025; --ok:#1e8e3e; --warn:#b26a00; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --card:#21211f; --text:#ededea; --muted:#a3a39d; --line:#34342f;
          --accent:#6f9cf0; --rec:#f2766b; --ok:#5bbf73; --warn:#e0a24a; } }
* { box-sizing:border-box; }
body { margin:0; font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
       background:var(--bg); color:var(--text); }
main { max-width:640px; margin:0 auto; padding:16px; }
h1 { font-size:22px; margin:8px 0 16px; } h2 { font-size:17px; margin:24px 0 8px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:16px; margin-bottom:12px; }
.big { display:block; width:100%; padding:22px; font-size:22px; font-weight:600;
       border:0; border-radius:14px; color:#fff; background:var(--accent); cursor:pointer; }
.big.stop { background:var(--rec); }
.muted { color:var(--muted); font-size:14px; }
.banner { border-left:4px solid var(--warn); }
.badge { display:inline-block; padding:2px 8px; border-radius:99px; font-size:13px;
         border:1px solid currentColor; }
.badge.ok { color:var(--ok); } .badge.bad { color:var(--rec); }
.badge.wait { color:var(--warn); } .badge.rec { color:var(--rec); }
.row { display:flex; justify-content:space-between; gap:8px; align-items:baseline;
       flex-wrap:wrap; }
.links a { margin-right:12px; }
a { color:var(--accent); }
label { display:block; margin:12px 0 4px; font-weight:600; }
input[type=text], input[type=password], input[type=number], input[type=email], select, textarea {
  width:100%; padding:10px; font-size:16px; border:1px solid var(--line); border-radius:8px;
  background:var(--bg); color:var(--text); }
.check { display:flex; gap:8px; align-items:center; font-weight:400; }
button.small { padding:8px 14px; font-size:15px; border-radius:8px; border:1px solid var(--line);
               background:var(--card); color:var(--text); cursor:pointer; }
pre { white-space:pre-wrap; word-wrap:break-word; font:14px/1.5 ui-monospace,monospace; }
.error { color:var(--rec); }
"""


def _page(title: str, body: str, refresh: Optional[int] = None) -> bytes:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ''
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'{meta}<title>{escape(title)}</title><style>{STYLE}</style></head>'
        f'<body><main>{body}</main></body></html>'
    )
    return html.encode('utf-8')


def _minutes(seconds: Optional[float]) -> str:
    if not seconds:
        return ''
    minutes = int(seconds // 60)
    return f"{minutes} min" if minutes else f"{int(seconds)} s"


def _job_date(job) -> str:
    if not job.started_at:
        return job.id
    return job.started_at.replace('T', ' ')[:16]


class Handler(BaseHTTPRequestHandler):
    service = None  # set by start_web_server

    def log_message(self, fmt, *args):
        log.debug("web: " + fmt, *args)

    # --- helpers -----------------------------------------------------------

    def _send(self, body: bytes, status: int = 200, ctype: str = 'text/html; charset=utf-8',
              headers: Optional[Dict[str, str]] = None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _form(self) -> Dict[str, str]:
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_FORM_BYTES:
            return {}
        raw = self.rfile.read(length).decode('utf-8', 'replace')
        return {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def _not_found(self):
        self._send(_page("Not found", "<h1>Not found</h1><p><a href='/'>Back</a></p>"), 404)

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            return self._home()
        if path == '/settings':
            return self._settings()
        if path == '/api/status':
            return self._api_status()
        if path.startswith('/meeting/'):
            return self._meeting(path[len('/meeting/'):])
        if path.startswith('/file/'):
            parts = path.split('/')
            if len(parts) == 4:
                return self._file(parts[2], parts[3])
        self._not_found()

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        svc = self.service
        if path == '/toggle':
            form = self._form()
            if form.get('action') == 'start':
                svc.start_meeting()
            elif form.get('action') == 'stop':
                svc.stop_meeting()
            return self._redirect('/')
        if path == '/retry':
            form = self._form()
            svc.retry(form.get('id') or None)
            return self._redirect('/')
        if path == '/settings':
            return self._save_settings(self._form())
        self._not_found()

    # --- pages -------------------------------------------------------------

    def _home(self):
        status = self.service.status()
        parts = ['<h1>Meeting Notetaker</h1>']

        if not status['api_key_set']:
            parts.append('<div class="card banner"><b>Setup needed.</b> Add your Mistral API '
                         'key so recordings can be turned into memos. '
                         '<a href="/settings">Open settings</a></div>')

        if status['recording']:
            limit = status['max_recording_minutes']
            parts.append(
                '<form method="post" action="/toggle"><input type="hidden" name="action" value="stop">'
                f'<button class="big stop">■ Stop meeting · {escape(_minutes(status["recording_seconds"]) or "0 s")}</button>'
                f'</form><p class="muted">Recording. Stops automatically after {limit} minutes.</p>'
            )
        else:
            parts.append(
                '<form method="post" action="/toggle"><input type="hidden" name="action" value="start">'
                '<button class="big">● Start meeting</button></form>'
                '<p class="muted">Or press the button on the device.</p>'
            )

        if status['last_event']:
            parts.append(f'<p class="muted">{escape(status["last_event"])}</p>')

        parts.append('<h2>Meetings</h2>')
        jobs = status['jobs']
        if not jobs:
            parts.append('<p class="muted">No meetings yet.</p>')
        if any(j.status == FAILED for j in jobs):
            parts.append('<form method="post" action="/retry"><button class="small">'
                         'Retry all problems</button></form><br>')
        for job in jobs[:30]:
            label, css = STATUS_LABELS.get(job.status, (job.status, 'wait'))
            title = escape(job.title or 'Meeting')
            jid = quote(job.id)
            links = []
            if job.memo_file and os.path.exists(job.memo_file):
                links.append(f'<a href="/meeting/{jid}">Memo</a>')
            if job.transcript_file and os.path.exists(job.transcript_file):
                links.append(f'<a href="/file/{jid}/transcript">Transcript</a>')
            if os.path.exists(job.audio_file):
                links.append(f'<a href="/file/{jid}/audio">Audio</a>')
            extra = ''
            if job.last_error and job.status != DONE:
                extra += f'<p class="error">{escape(job.last_error)}</p>'
            if job.status == PENDING and job.attempts:
                extra += '<p class="muted">Will retry automatically.</p>'
            if job.status == FAILED:
                extra += (f'<form method="post" action="/retry"><input type="hidden" name="id" '
                          f'value="{escape(job.id)}"><button class="small">Retry</button></form>')
            if job.status == DONE and job.emailed:
                extra += '<p class="muted">Sent by email.</p>'
            parts.append(
                f'<div class="card"><div class="row"><b>{title}</b>'
                f'<span class="badge {css}">{escape(label)}</span></div>'
                f'<div class="muted">{escape(_job_date(job))} · {escape(_minutes(job.duration))}</div>'
                f'<div class="links">{" ".join(links)}</div>{extra}</div>'
            )

        parts.append('<p><a href="/settings">Settings</a></p>')
        busy = status['recording'] or any(j.status in (PENDING, PROCESSING) for j in jobs)
        self._send(_page("Meeting Notetaker", ''.join(parts), refresh=5 if busy else 30))

    def _meeting(self, job_id: str):
        job = self.service.store.get(job_id)
        if not job or not job.memo_file or not os.path.exists(job.memo_file):
            return self._not_found()
        with open(job.memo_file, encoding='utf-8') as f:
            memo = f.read()
        jid = quote(job.id)
        body = (f'<p><a href="/">← Back</a></p><div class="card"><pre>{escape(memo)}</pre></div>'
                f'<p class="links"><a href="/file/{jid}/memo">Download memo</a>'
                f'<a href="/file/{jid}/transcript">Transcript</a>'
                f'<a href="/file/{jid}/audio">Audio</a></p>')
        self._send(_page(job.title or "Memo", body))

    def _file(self, job_id: str, kind: str):
        job = self.service.store.get(job_id)
        paths = {
            'memo': (job.memo_file, 'text/markdown; charset=utf-8') if job else None,
            'transcript': (job.transcript_file, 'text/plain; charset=utf-8') if job else None,
            'audio': (job.audio_file, 'audio/wav') if job else None,
        }
        entry = paths.get(kind)
        if not entry or not entry[0] or not os.path.exists(entry[0]):
            return self._not_found()
        path, ctype = entry
        # Stream: a two-hour recording is ~230 MB
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(os.path.getsize(path)))
        self.send_header('Content-Disposition',
                         f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _api_status(self):
        status = self.service.status()
        status['jobs'] = [{
            'id': j.id, 'status': j.status, 'title': j.title, 'started_at': j.started_at,
            'duration': j.duration, 'error': j.last_error, 'emailed': j.emailed,
        } for j in status['jobs']]
        self._send(json.dumps(status).encode(), ctype='application/json')

    # --- settings ----------------------------------------------------------

    def _settings(self, message: str = '', error: bool = False):
        c = self.service.config
        first_visit = not c.web.pin
        e = c.email

        def field(name, label, value='', kind='text', hint=''):
            hint_html = f'<div class="muted">{escape(hint)}</div>' if hint else ''
            return (f'<label for="{name}">{escape(label)}</label>{hint_html}'
                    f'<input id="{name}" name="{name}" type="{kind}" value="{escape(str(value))}" '
                    f'autocomplete="off">')

        def check(name, label, on):
            return (f'<label class="check"><input type="checkbox" name="{name}" value="1"'
                    f'{" checked" if on else ""}> {escape(label)}</label>')

        lang_options = ''.join(
            f'<option value="{v}"{" selected" if c.service.language == v else ""}>{escape(t)}</option>'
            for v, t in LANGUAGES)
        key_hint = "Saved. Leave empty to keep it." if c.voxtral.api_key else \
            "From Mistral AI Studio (console.mistral.ai)."
        pw_hint = "Saved. Leave empty to keep it." if e.smtp_password else ""

        msg_html = ''
        if message:
            msg_html = f'<div class="card {"banner" if error else ""}">{escape(message)}</div>'
        pin_html = (field('new_pin', 'Choose a PIN (at least 4 digits)', kind='password',
                          hint='Needed to change these settings later. Write it down.')
                    if first_visit else
                    field('pin', 'PIN', kind='password', hint='Required to save.'))

        body = f"""
<p><a href="/">← Back</a></p><h1>Settings</h1>{msg_html}
<form method="post" action="/settings">
<div class="card"><h2>Transcription</h2>
{field('api_key', 'Mistral API key', '', 'password', key_hint)}
<label for="language">Meeting language</label>
<select id="language" name="language">{lang_options}</select>
{field('max_minutes', 'Stop recording automatically after (minutes)', c.max_recording_minutes, 'number')}
</div>
<div class="card"><h2>Email the memo</h2>
{check('email_enabled', 'Send the memo by email after each meeting', e.enabled)}
<label for="to_emails">Send to</label><div class="muted">One address per line.</div>
<textarea id="to_emails" name="to_emails" rows="3">{escape(chr(10).join(e.to_emails))}</textarea>
{field('smtp_host', 'SMTP server', e.smtp_host, hint='e.g. smtp.gmail.com, smtp.office365.com')}
{field('smtp_port', 'SMTP port', e.smtp_port, 'number', '587 (STARTTLS) or 465 (SSL)')}
{field('smtp_user', 'SMTP user', e.smtp_user)}
{field('smtp_password', 'SMTP password', '', 'password', pw_hint)}
{field('from_email', 'From address', e.from_email)}
{check('attach_transcript', 'Attach the transcript', e.attach_transcript)}
{check('attach_audio', 'Attach the audio (large)', e.attach_audio)}
</div>
<div class="card"><h2>Wi-Fi</h2><div class="muted">Only to change the network. Leave empty otherwise.</div>
{field('wifi_ssid', 'Network name')}
{field('wifi_password', 'Wi-Fi password', '', 'password')}
</div>
<div class="card">{pin_html}
{'' if first_visit else field('new_pin', 'New PIN (optional)', kind='password')}
<br><button class="big">Save</button></div>
</form>"""
        self._send(_page("Settings", body))

    def _save_settings(self, form: Dict[str, str]):
        svc = self.service
        current = svc.config

        if current.web.pin:
            if not hmac.compare_digest(form.get('pin', ''), current.web.pin):
                time.sleep(1)  # slow down guessing
                return self._settings("Wrong PIN. Nothing was saved.", error=True)
        elif len(form.get('new_pin', '')) < 4 or not form.get('new_pin', '').isdigit():
            return self._settings("Please choose a PIN of at least 4 digits.", error=True)

        config = NotetakerConfig.from_dict(current.to_dict())  # edit a copy
        if form.get('api_key', '').strip():
            config.voxtral.api_key = form['api_key'].strip()
        language = form.get('language', 'auto')
        if language in {v for v, _ in LANGUAGES}:
            config.service.language = language
        try:
            minutes = int(form.get('max_minutes') or config.max_recording_minutes)
            config.max_recording_minutes = max(5, min(minutes, 600))
        except ValueError:
            pass

        e = config.email
        e.enabled = form.get('email_enabled') == '1'
        e.to_emails = [a.strip() for a in form.get('to_emails', '').replace(',', '\n').splitlines()
                       if a.strip()]
        e.smtp_host = form.get('smtp_host', '').strip()
        try:
            e.smtp_port = int(form.get('smtp_port') or 587)
        except ValueError:
            pass
        e.smtp_user = form.get('smtp_user', '').strip()
        if form.get('smtp_password'):
            e.smtp_password = form['smtp_password']
        e.from_email = form.get('from_email', '').strip()
        e.attach_transcript = form.get('attach_transcript') == '1'
        e.attach_audio = form.get('attach_audio') == '1'

        if form.get('new_pin'):
            if len(form['new_pin']) < 4 or not form['new_pin'].isdigit():
                return self._settings("The new PIN needs at least 4 digits.", error=True)
            config.web.pin = form['new_pin']

        problems = []
        if e.enabled and (not e.to_emails or not e.smtp_host):
            problems.append("Email is on, but the recipients or SMTP server are missing.")

        svc.update_config(config)

        message = "Saved."
        if form.get('wifi_ssid', '').strip():
            ssid, password = form['wifi_ssid'].strip(), form.get('wifi_password', '')
            from .network import connect_wifi
            threading.Thread(target=connect_wifi, args=(ssid, password), daemon=True).start()
            message += (f" Connecting to Wi-Fi '{ssid}'. If this page stops loading, reconnect "
                        f"your phone to that network and open the device's address again.")
        if problems:
            message += " " + " ".join(problems)
        self._settings(message, error=bool(problems))


def start_web_server(service, host: Optional[str] = None, port: Optional[int] = None):
    """Start the web page in a background thread; returns the server"""
    handler = type('BoundHandler', (Handler,), {'service': service})
    server = ThreadingHTTPServer((host or service.config.web.host,
                                  service.config.web.port if port is None else port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    log.info("Web page on port %s", server.server_address[1])
    return server
