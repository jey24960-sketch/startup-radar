"""Acceptance probe for the evidence image; contains no source/network acquisition."""
import json
import os
from pathlib import Path
import socket


def main():
    try:
        with socket.create_connection(('192.0.2.1',443),timeout=1):network_blocked=False
    except OSError:network_blocked=True
    try:
        Path('/app/probe-write').write_text('must fail')
        root_read_only=False
    except OSError:root_read_only=True
    print(json.dumps({'secrets_absent':not any(os.environ.get(k) for k in ('DATABASE_URL','ANTHROPIC_API_KEY','TELEGRAM_BOT_TOKEN')),
                      'network_blocked':network_blocked,'root_read_only':root_read_only,'non_root':os.getuid()!=0}))


if __name__=='__main__':main()
