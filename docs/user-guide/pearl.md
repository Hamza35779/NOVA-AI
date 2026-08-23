# Pearl CLI Integration

NOVA AI includes a thin `nova pearl` wrapper for Pearl's native command
line tools. It does not replace Pearl's node or wallet; it makes the common
commands discoverable from the same CLI users use for mining.

## Binary Discovery

`nova pearl` looks for `pearld`, `oyster`, and `prlctl` on `PATH`, then under
`$PEARL_HOME/bin`.

```bash
export PEARL_HOME=/path/to/pearl
nova pearl doctor
```

## Native Pass-Through

Use pass-through commands when you need the full Pearl surface:

```bash
nova pearl node -- --help
nova pearl wallet -- --help
nova pearl ctl -- --help
```

These map directly to:

| NOVA AI command | Pearl binary |
|---|---|
| `nova pearl node` | `pearld` |
| `nova pearl wallet` | `oyster` |
| `nova pearl ctl` | `prlctl` |

The command format is always `nova pearl <command>`. Pearl-native arguments
go after that command. Use `--` before Pearl arguments when the arguments begin
with dashes and you want to make the pass-through boundary explicit.

## Wallet Address Helper

If Oyster is already running, generate a mining address through wallet RPC:

```bash
nova pearl address \
  -u rpcuser \
  -P rpcpass \
  -s localhost:44207
```

The helper uses `prlctl --wallet` and defaults to `--notls`, which matches the
local validation flow. Use `--tls --skipverify` if your Oyster RPC endpoint is
serving TLS with a local certificate.

## Boundary

`nova mine` is the NOVA AI mining lifecycle. `nova pearl` is an escape
hatch to Pearl's native node, wallet, and RPC tools. For advanced node or
wallet administration, Pearl's own help output is the source of truth.
