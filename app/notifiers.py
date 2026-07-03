import requests
from datetime import datetime, timezone


def _device_detail(payload):
    payload = payload or {}
    name = payload.get('name') or payload.get('hostname') or payload.get('mac') or 'Unknown device'
    mac = payload.get('mac') or 'unknown-mac'
    ip = payload.get('ip') or payload.get('last_ip') or 'unknown-ip'
    network = payload.get('network_id') or 'unknown-network'
    profile = payload.get('profile') or 'no-profile'
    return name, mac, ip, network, profile


def send(config, text, payload=None):
    n = config.get('notifications', {}) or {}
    payload = payload or {}
    name, mac, ip, network, profile = _device_detail(payload)
    ts = datetime.now(timezone.utc).isoformat()

    slack_body = {
        'text': text,
        'blocks': [
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': f'*eero Presence Change*\n{text}'
                }
            },
            {
                'type': 'section',
                'fields': [
                    {'type': 'mrkdwn', 'text': f'*Device:*\n{name}'},
                    {'type': 'mrkdwn', 'text': f'*MAC:*\n`{mac}`'},
                    {'type': 'mrkdwn', 'text': f'*IP:*\n`{ip}`'},
                    {'type': 'mrkdwn', 'text': f'*Profile:*\n{profile}'},
                    {'type': 'mrkdwn', 'text': f'*Network:*\n{network}'},
                    {'type': 'mrkdwn', 'text': f'*UTC:*\n{ts}'},
                ]
            }
        ],
        'payload': payload,
    }

    for url in n.get('webhook_urls') or []:
        if url:
            requests.post(url, json=slack_body, timeout=8)

    if n.get('pushcut_url'):
        requests.post(n['pushcut_url'], json={'text': text, **payload}, timeout=8)
