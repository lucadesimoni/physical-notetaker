# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Setup and status page, made for a phone: http://<device> (port 80 after install)

- Big start/stop button, the meetings with their memos, free storage
- Correct speaker names and remake a memo without transcribing again
- Printable sticker with QR codes for the device
- Settings (API key, email, language, Wi-Fi) behind a PIN chosen on first visit

The phone needs to be in the same network as the device (or in the device's
setup hotspot).
"""

import os
import hmac
import time
import json
import logging
import threading
from html import escape
from urllib.parse import parse_qs, quote, unquote
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional

from .config import NotetakerConfig
from .jobs import DONE, FAILED, PENDING, PROCESSING, RECORDING
from .i18n import t, normalize

log = logging.getLogger(__name__)

MAX_FORM_BYTES = 64 * 1024
MEETING_LANGUAGES = ['auto', 'de-CH', 'de', 'en']
STATUS_CSS = {RECORDING: 'rec', PENDING: 'wait', PROCESSING: 'wait', DONE: 'ok', FAILED: 'bad'}

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
.sticker { background:#fff; color:#000; border:2px dashed #999; border-radius:12px;
           padding:20px; max-width:420px; }
.sticker h1 { margin-top:0; }
.sticker ol { padding-left:22px; font-size:18px; line-height:1.6; }
.qr { display:flex; gap:16px; flex-wrap:wrap; align-items:flex-end; }
.qr div { text-align:center; font-size:13px; word-break:break-all; max-width:180px; }
@media print { .noprint { display:none; } body { background:#fff; } .sticker { border-color:#ccc; } }
"""


def _page(title: str, body: str, lang: str, refresh: Optional[int] = None) -> bytes:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ''
    html = (
        f'<!doctype html><html lang="{normalize(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'{meta}<title>{escape(title)}</title><style>{STYLE}</style></head>'
        f'<body><main>{body}</main></body></html>'
    )
    return html.encode('utf-8')


def _job_date(job) -> str:
    if not job.started_at:
        return job.id
    return job.started_at.replace('T', ' ')[:16]


def qr_svg(text: str) -> Optional[str]:
    """Inline SVG QR code, or None when segno is not installed"""
    try:
        import segno
    except ImportError:
        return None
    return segno.make(text, error='m').svg_inline(scale=5, border=2, dark='#000', light='#fff')


class Handler(BaseHTTPRequestHandler):
    service = None  # set by start_web_server

    def log_message(self, fmt, *args):
        log.debug("web: " + fmt, *args)

    @property
    def lang(self) -> str:
        return self.service.config.service.ui_language

    def t(self, key: str, **kwargs) -> str:
        return t(key, self.lang, **kwargs)

    def _duration(self, seconds: Optional[float]) -> str:
        if not seconds:
            return ''
        minutes = int(seconds // 60)
        if minutes:
            return self.t('minutes_short', n=minutes)
        return self.t('seconds_short', n=int(seconds))

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

    def _html(self, title: str, body: str, refresh: Optional[int] = None):
        self._send(_page(title, body, self.lang, refresh))

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
        self._send(_page(self.t('not_found'), f"<h1>{escape(self.t('not_found'))}</h1>"
                         f"<p><a href='/'>{escape(self.t('back'))}</a></p>", self.lang), 404)

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            return self._home()
        if path == '/settings':
            return self._settings()
        if path == '/sticker':
            return self._sticker()
        if path == '/api/status':
            return self._api_status()
        if path.startswith('/meeting/'):
            return self._meeting(unquote(path[len('/meeting/'):]))
        if path.startswith('/file/'):
            parts = path.split('/')
            if len(parts) == 4:
                return self._file(unquote(parts[2]), parts[3])
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
        if path.startswith('/meeting/') and path.endswith('/speakers'):
            job_id = unquote(path[len('/meeting/'):-len('/speakers')])
            return self._save_speakers(job_id, self._form())
        self._not_found()

    # --- pages -------------------------------------------------------------

    def _home(self):
        status = self.service.status()
        parts = [f'<h1>{escape(self.t("app_title"))}</h1>']

        if not status['api_key_set']:
            parts.append(f'<div class="card banner"><b>{escape(self.t("setup_needed"))}</b> '
                         f'{escape(self.t("setup_needed_text"))} '
                         f'<a href="/settings">{escape(self.t("open_settings"))}</a></div>')
        if status['storage_low']:
            parts.append(f'<div class="card banner">'
                         f'{escape(self.t("storage_low", free=status["free_text"]))}</div>')

        if status['recording']:
            elapsed = self._duration(status['recording_seconds']) or self.t('seconds_short', n=0)
            parts.append(
                '<form method="post" action="/toggle"><input type="hidden" name="action" value="stop">'
                f'<button class="big stop">{escape(self.t("stop_meeting", elapsed=elapsed))}</button>'
                f'</form><p class="muted">'
                f'{escape(self.t("recording_hint", minutes=status["max_recording_minutes"]))}</p>'
            )
            if status['live_items']:
                items = ''.join(f'<li>{escape(text)}</li>' for _, text in status['live_items'][-5:])
                parts.append(f'<div class="card"><ul>{items}</ul></div>')
        else:
            parts.append(
                '<form method="post" action="/toggle"><input type="hidden" name="action" value="start">'
                f'<button class="big">{escape(self.t("start_meeting"))}</button></form>'
                f'<p class="muted">{escape(self.t("start_hint"))}</p>'
            )

        if status['last_event']:
            parts.append(f'<p class="muted">{escape(status["last_event"])}</p>')

        parts.append(f'<h2>{escape(self.t("meetings"))}</h2>')
        jobs = status['jobs']
        if not jobs:
            parts.append(f'<p class="muted">{escape(self.t("no_meetings"))}</p>')
        if any(j.status == FAILED for j in jobs):
            parts.append(f'<form method="post" action="/retry"><button class="small">'
                         f'{escape(self.t("retry_all"))}</button></form><br>')
        days = self.service.config.service.keep_audio_days
        for job in jobs[:30]:
            css = STATUS_CSS.get(job.status, 'wait')
            label = self.t(f'status_{job.status}')
            title = escape(job.title or self.t('meeting_default_title'))
            jid = quote(job.id)
            links = []
            if job.memo_file and os.path.exists(job.memo_file):
                links.append(f'<a href="/meeting/{jid}">{escape(self.t("memo"))}</a>')
            if job.transcript_file and os.path.exists(job.transcript_file):
                links.append(f'<a href="/file/{jid}/transcript">{escape(self.t("transcript"))}</a>')
            if os.path.exists(job.audio_file):
                links.append(f'<a href="/file/{jid}/audio">{escape(self.t("audio"))}</a>')
            extra = ''
            if job.last_error and job.status != DONE:
                extra += f'<p class="error">{escape(job.last_error)}</p>'
            if job.status == PENDING and job.attempts:
                extra += f'<p class="muted">{escape(self.t("will_retry"))}</p>'
            if job.status == FAILED:
                extra += (f'<form method="post" action="/retry"><input type="hidden" name="id" '
                          f'value="{escape(job.id)}"><button class="small">'
                          f'{escape(self.t("retry"))}</button></form>')
            if job.status == DONE and job.emailed:
                extra += f'<p class="muted">{escape(self.t("sent_by_email"))}</p>'
            if job.audio_deleted:
                extra += f'<p class="muted">{escape(self.t("audio_deleted", days=days))}</p>'
            parts.append(
                f'<div class="card"><div class="row"><b>{title}</b>'
                f'<span class="badge {css}">{escape(label)}</span></div>'
                f'<div class="muted">{escape(_job_date(job))} · {escape(self._duration(job.duration))}</div>'
                f'<div class="links">{" ".join(links)}</div>{extra}</div>'
            )

        parts.append(f'<p class="muted">{escape(self.t("storage_free", free=status["free_text"]))}</p>')
        parts.append(f'<p class="links"><a href="/settings">{escape(self.t("settings"))}</a>'
                     f'<a href="/sticker">{escape(self.t("sticker"))}</a></p>')
        busy = status['recording'] or any(j.status in (PENDING, PROCESSING) for j in jobs)
        self._html(self.t('app_title'), ''.join(parts), refresh=5 if busy else 30)

    def _meeting(self, job_id: str, message: str = ''):
        job = self.service.store.get(job_id)
        if not job:
            return self._not_found()
        jid = quote(job.id)
        parts = [f'<p><a href="/">{escape(self.t("back"))}</a></p>']
        if message:
            parts.append(f'<div class="card">{escape(message)}</div>')
        if job.memo_file and os.path.exists(job.memo_file):
            with open(job.memo_file, encoding='utf-8') as f:
                memo = f.read()
            parts.append(f'<div class="card"><pre>{escape(memo)}</pre></div>')
        else:
            parts.append(f'<div class="card">{escape(self.t("status_" + job.status))}</div>')

        if job.speakers and job.status not in (RECORDING, PROCESSING):
            rows = []
            for i, (speaker_id, name) in enumerate(sorted(job.speakers.items())):
                current = job.speaker_overrides.get(speaker_id, name)
                rows.append(
                    f'<input type="hidden" name="id_{i}" value="{escape(speaker_id)}">'
                    f'<label for="name_{i}">{escape(speaker_id)}</label>'
                    f'<input id="name_{i}" name="name_{i}" type="text" value="{escape(current)}">'
                )
            resend = (f'<label class="check"><input type="checkbox" name="resend" value="1" checked>'
                      f' {escape(self.t("resend_email"))}</label>'
                      if self.service.config.email.ready else '')
            parts.append(
                f'<div class="card"><h2>{escape(self.t("speakers"))}</h2>'
                f'<p class="muted">{escape(self.t("speakers_hint"))}</p>'
                f'<form method="post" action="/meeting/{jid}/speakers">{"".join(rows)}{resend}'
                f'<br><button class="small">{escape(self.t("remake_memo"))}</button></form></div>'
            )

        parts.append(
            f'<p class="links"><a href="/file/{jid}/memo">{escape(self.t("download_memo"))}</a>'
            f'<a href="/file/{jid}/transcript">{escape(self.t("transcript"))}</a>'
            f'<a href="/file/{jid}/audio">{escape(self.t("audio"))}</a></p>'
        )
        refresh = 5 if job.status in (PENDING, PROCESSING) else None
        self._html(job.title or self.t('memo'), ''.join(parts), refresh=refresh)

    def _save_speakers(self, job_id: str, form: Dict[str, str]):
        names = {}
        i = 0
        while f'id_{i}' in form:
            names[form[f'id_{i}']] = form.get(f'name_{i}', '')[:80]
            i += 1
        resend = form.get('resend') == '1'
        if self.service.remake_memo(job_id, names, resend_email=resend):
            return self._meeting(job_id, self.t('remake_started'))
        return self._meeting(job_id)

    def _sticker(self):
        from .network import device_urls
        urls = device_urls(self.service.config.web.port)
        codes = []
        for url in urls:
            svg = qr_svg(url)
            codes.append(f'<div>{svg or ""}<br>{escape(url)}</div>')
        steps = ''.join(f'<li>{escape(self.t(k))}</li>'
                        for k in ('sticker_step1', 'sticker_step2', 'sticker_step3'))
        body = (
            f'<p class="noprint"><a href="/">{escape(self.t("back"))}</a> · '
            f'{escape(self.t("sticker_print"))}</p>'
            f'<div class="sticker"><h1>{escape(self.t("sticker_title"))}</h1><ol>{steps}</ol>'
            f'<p>{escape(self.t("sticker_long_press"))}</p>'
            f'<p>{escape(self.t("sticker_scan"))}</p><div class="qr">{"".join(codes)}</div></div>'
        )
        self._html(self.t('sticker'), body)

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

        def field(name, label_key, value='', kind='text', hint=''):
            hint_html = f'<div class="muted">{escape(hint)}</div>' if hint else ''
            return (f'<label for="{name}">{escape(self.t(label_key))}</label>{hint_html}'
                    f'<input id="{name}" name="{name}" type="{kind}" value="{escape(str(value))}" '
                    f'autocomplete="off">')

        def check(name, label_key, on, hint=''):
            hint_html = f'<div class="muted">{escape(hint)}</div>' if hint else ''
            return (f'<label class="check"><input type="checkbox" name="{name}" value="1"'
                    f'{" checked" if on else ""}> {escape(self.t(label_key))}</label>{hint_html}')

        def select(name, label_key, options, current):
            opts = ''.join(f'<option value="{escape(v)}"{" selected" if current == v else ""}>'
                           f'{escape(text)}</option>' for v, text in options)
            return (f'<label for="{name}">{escape(self.t(label_key))}</label>'
                    f'<select id="{name}" name="{name}">{opts}</select>')

        key_hint = self.t('api_key_saved') if c.voxtral.api_key else self.t('api_key_hint')
        pw_hint = self.t('api_key_saved') if e.smtp_password else ''
        msg_html = ''
        if message:
            msg_html = f'<div class="card {"banner" if error else ""}">{escape(message)}</div>'
        if first_visit:
            pin_html = field('new_pin', 'choose_pin', kind='password', hint=self.t('choose_pin_hint'))
        else:
            pin_html = (field('pin', 'pin', kind='password', hint=self.t('pin_hint')) +
                        field('new_pin', 'new_pin', kind='password'))
        meeting_langs = [(v, self.t(f'lang_{v}')) for v in MEETING_LANGUAGES]
        ui_langs = [('de', 'Deutsch'), ('en', 'English')]

        body = f"""
<p><a href="/">{escape(self.t('back'))}</a></p><h1>{escape(self.t('settings'))}</h1>{msg_html}
<form method="post" action="/settings">
<div class="card"><h2>{escape(self.t('transcription'))}</h2>
{field('api_key', 'api_key', '', 'password', key_hint)}
{select('language', 'meeting_language', meeting_langs, c.service.language)}
{select('ui_language', 'ui_language', ui_langs, normalize(c.service.ui_language))}
{field('max_minutes', 'max_minutes', c.max_recording_minutes, 'number')}
{field('keep_audio_days', 'keep_audio_days', c.service.keep_audio_days, 'number', self.t('keep_audio_hint'))}
</div>
<div class="card"><h2>{escape(self.t('voice_section'))}</h2>
{check('voice', 'voice_enabled', c.device.voice)}
{check('live_commands', 'live_commands', c.service.live_commands,
       self.t('live_commands_hint', seconds=c.service.live_interval_seconds))}
</div>
<div class="card"><h2>{escape(self.t('email_section'))}</h2>
{check('email_enabled', 'email_enabled', e.enabled)}
<label for="to_emails">{escape(self.t('send_to'))}</label>
<div class="muted">{escape(self.t('one_per_line'))}</div>
<textarea id="to_emails" name="to_emails" rows="3">{escape(chr(10).join(e.to_emails))}</textarea>
{field('smtp_host', 'smtp_host', e.smtp_host, hint='smtp.gmail.com, smtp.office365.com, mail.infomaniak.com')}
{field('smtp_port', 'smtp_port', e.smtp_port, 'number', self.t('smtp_port_hint'))}
{field('smtp_user', 'smtp_user', e.smtp_user)}
{field('smtp_password', 'email_password', '', 'password', pw_hint or self.t('email_password_hint'))}
{field('from_email', 'email_account', e.from_email)}
{check('attach_transcript', 'attach_transcript', e.attach_transcript)}
{check('attach_audio', 'attach_audio', e.attach_audio)}
</div>
<div class="card"><h2>{escape(self.t('wifi'))}</h2><div class="muted">{escape(self.t('wifi_hint'))}</div>
{field('wifi_ssid', 'wifi_ssid')}
{field('wifi_password', 'wifi_password', '', 'password')}
</div>
<div class="card">{pin_html}
<br><button class="big">{escape(self.t('save'))}</button></div>
</form>"""
        self._html(self.t('settings'), body)

    def _save_settings(self, form: Dict[str, str]):
        svc = self.service
        current = svc.config

        if current.web.pin:
            if not hmac.compare_digest(form.get('pin', ''), current.web.pin):
                time.sleep(1)  # slow down guessing
                return self._settings(self.t('wrong_pin'), error=True)
        elif len(form.get('new_pin', '')) < 4 or not form.get('new_pin', '').isdigit():
            return self._settings(self.t('pin_too_short'), error=True)

        config = NotetakerConfig.from_dict(current.to_dict())  # edit a copy
        if form.get('api_key', '').strip():
            config.voxtral.api_key = form['api_key'].strip()
        if form.get('language') in MEETING_LANGUAGES:
            config.service.language = form['language']
        if form.get('ui_language') in ('de', 'en'):
            config.service.ui_language = form['ui_language']

        def number(name, low, high, default):
            try:
                return max(low, min(int(form.get(name) or default), high))
            except ValueError:
                return default

        config.max_recording_minutes = number('max_minutes', 5, 600, config.max_recording_minutes)
        config.service.keep_audio_days = number('keep_audio_days', 0, 3650,
                                                config.service.keep_audio_days)
        config.device.voice = form.get('voice') == '1'
        config.service.live_commands = form.get('live_commands') == '1'

        e = config.email
        e.enabled = form.get('email_enabled') == '1'
        e.to_emails = [a.strip() for a in form.get('to_emails', '').replace(',', '\n').splitlines()
                       if a.strip()]
        e.smtp_host = form.get('smtp_host', '').strip()
        e.smtp_port = number('smtp_port', 1, 65535, e.smtp_port)
        e.smtp_user = form.get('smtp_user', '').strip()
        if form.get('smtp_password'):
            e.smtp_password = form['smtp_password']
        e.from_email = form.get('from_email', '').strip()
        e.attach_transcript = form.get('attach_transcript') == '1'
        e.attach_audio = form.get('attach_audio') == '1'

        if form.get('new_pin'):
            if len(form['new_pin']) < 4 or not form['new_pin'].isdigit():
                return self._settings(self.t('pin_too_short'), error=True)
            config.web.pin = form['new_pin']

        problems = []
        if e.enabled and (not e.to_emails or not e.smtp_host):
            problems.append(t('email_incomplete', config.service.ui_language))

        svc.update_config(config)

        message = t('saved', config.service.ui_language)
        if form.get('wifi_ssid', '').strip():
            ssid, password = form['wifi_ssid'].strip(), form.get('wifi_password', '')
            from .network import connect_wifi
            threading.Thread(target=connect_wifi, args=(ssid, password), daemon=True).start()
            message += " " + t('wifi_connecting', config.service.ui_language, ssid=ssid)
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
