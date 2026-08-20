# EEF Node (`eefn`)

The **standalone node** runtime — the flat, self-contained package that installs into
`C:/eefn` on a fresh PC and links it to the EEF coordinator. It needs **no EEF package**;
just Python 3.11+ and `cryptography` (for AES-256-GCM links). The coordinator clone is the
companion repo (eef).

## What's here

| File | Role |
|---|---|
| `node_crypto.py` | AES-256-GCM + HMAC over a PSK-derived key |
| `node_protocol.py` | newline-JSON wire protocol (auth/register/heartbeat/request/response) |
| `node_engine.py` | capabilities a PC node offers: `system.ping`, `filesystem`, `launch_application`, `llm.infer`, `vlm.analyze` |
| `node_client.py` | long-running client: ordered-endpoint failover, signed AUTH, register, heartbeat, serve loop |
| `run_node.py` | entry point (reads `config.json`) |
| `start.cmd` | double-click launcher |
| `bootstrap_eef.py` | single-file installer for a brand-new node |
| `install.ps1` | PowerShell wrapper (`irm … \| iex`) |
| `make_node_dist.py` | build `dist/eef-node-dist.zip` from this repo |

## Provision a brand-new node (one command)

```powershell
powershell -nop -c "irm http://26.234.244.3:8081/api/node/install.ps1 | iex"
# or: python bootstrap_eef.py --from http://26.234.244.3:8081 --psk SECRET
```

Pulls the node package, extracts to `C:/eefn`, writes `config.json`
(`node_id`, `name`, `psk`, ordered endpoints **Radmin → Playit**), ensures `cryptography`.

## Run a provisioned node

```bash
cd C:\eefn
python run_node.py                 # connects and starts serving
python run_node.py --allow-write   # also allow filesystem writes
```

## Endpoints

`node.eeftuna.playit.plus` (secondary/other devices, TCP) and the Radmin VPN
(`26.234.244.3:8081`, primary for PC nodes) both end at the coordinator's node gateway.

## Security

- Every message **AES-256-GCM** encrypted (shared PSK). No plaintext/XOR fallback.
- Nodes authenticate with a **signed AUTH** handshake (HMAC over
  `nonce|node_id|version|timestamp`). Wrong key → encrypted `denied` + drop.
- `filesystem.write` is denied unless you run with `--allow-write`.