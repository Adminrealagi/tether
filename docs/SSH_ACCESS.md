# SSH Access

Tether can expose a key-authenticated SSH control prompt alongside the web UI and
messaging bridges. This does not provide a host shell. It exposes a small command
surface for controlling Tether sessions remotely.

## Install

```bash
pip install tether-ai[ssh]
```

## Configuration

```bash
TETHER_SSH_ENABLED=1
TETHER_SSH_HOST=0.0.0.0
TETHER_SSH_PORT=8822
TETHER_SSH_HOST_KEY_PATH=~/.local/share/tether/ssh_host_ed25519_key
TETHER_SSH_AUTHORIZED_KEYS_PATH=~/.local/share/tether/ssh_authorized_keys
```

- `TETHER_SSH_ENABLED` turns the server on at startup.
- `TETHER_SSH_HOST_KEY_PATH` points at the SSH host private key. If the file is
  missing, Tether generates an ed25519 host key with `ssh-keygen`.
- `TETHER_SSH_AUTHORIZED_KEYS_PATH` must contain one or more client public keys.

## Connecting

```bash
ssh -p 8822 localhost
ssh -p 8822 localhost 'list'
```

## Commands

- `help`
- `list`
- `pending <session-id-prefix>`
- `input <session-id-prefix> <text>`
- `interrupt <session-id-prefix>`
- `approve <session-id-prefix> <request-id> <allow|deny> [message]`
- `watch <session-id-prefix>`

Session IDs accept unique prefixes, matching the CLI and HTTP API behavior.

## Security model

- Authentication is public-key only.
- Authorization is file-based through `TETHER_SSH_AUTHORIZED_KEYS_PATH`.
- The SSH entrypoint is a Tether command prompt, not a general-purpose shell.
