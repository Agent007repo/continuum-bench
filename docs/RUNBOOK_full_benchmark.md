# Mac preflight and full-benchmark runbook

Status: preparation only. `make bench-full` currently refuses to run. No overnight duration or model-download footprint has been measured. We will estimate these from a pilot after choosing verified model configurations.

Run these read-only commands on your Mac and return the output. They contain no serial-number or identity query.

```bash
sw_vers
df -h "$HOME"
sysctl -n hw.memsize
command -v powermetrics
powermetrics --help
```

The hardware brief specifies an M1 Max with 64 GB unified memory. Free disk and Metal working-set limits are unknown. Do not download a large model collection yet. Weight files, quantisation and KV cache must be budgeted per configuration, and actual model revisions and licences must be recorded.

After adapter validation, a local operator can run powermetrics with sudo using a fixed sampling command selected from the installed help. We will request a separate permission-free readout of its supported samplers first. Never provide a password to this chat, pipe it into a command or grant blanket sudo to a script. No sampler command is presented as tested on your machine yet.

For a pilot, plug into power, record battery/power mode, close unrelated workloads, record thermal conditions, establish a timed idle baseline, and preserve raw samples. Exclude and log swapping rather than reporting a configuration that paged through disk. Validate request-clock alignment and gaps before trusting joules. If a wall-plug meter exists, prepare an independent validation window; otherwise state the component-energy limitation.

The final runbook will provide native and emulated-edge commands, a frozen configuration, resumption semantics, expected duration from measured pilot timings and calibration tasks. Those instructions cannot be claimed complete now.
