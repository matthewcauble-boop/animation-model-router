"""hf_run: call a Hugging Face Space (Gradio) with your token, or list its API, with a dry-run.

    pip install gradio_client huggingface_hub
    python tools/hf_run.py SPACE --view                         # print the Space's endpoints and their inputs
    python tools/hf_run.py SPACE --api /predict --inputs '["@img", "a prompt", 42]' --file img=frames/S1.png [--dry-run]

SPACE is "owner/space-name". "@name" in --inputs is replaced by gradio_client.handle_file(path) for --file name=path.
Token: HF_TOKEN from the environment (or .env). A PRO account gets a larger ZeroGPU quota; a free account queues
behind it and may hit the daily GPU limit. The call runs on the Space owner's hardware under the Space's licence and
the model's licence: read both before using the output for anything public.

Spaces change their API without notice: run --view first and match --api and the input order to what it prints.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = Path(os.environ.get("AMR_ENV_FILE", ".env"))
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines() if env.exists() else []:
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"') or None
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("space"); ap.add_argument("--view", action="store_true"); ap.add_argument("--api", default="/predict")
    ap.add_argument("--inputs", default="[]"); ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    files = dict(f.split("=", 1) for f in a.file)
    inputs = json.loads(a.inputs)
    if a.dry_run:
        print(f"would call {a.space} {a.api} with", [f"<file {files[x[1:]]}>" if isinstance(x, str) and x[1:] in files else x for x in inputs])
        return
    from gradio_client import Client, handle_file
    client = Client(a.space, hf_token=env_key("HF_TOKEN"))
    if a.view:
        client.view_api(); return
    args = [handle_file(files[x[1:]]) if isinstance(x, str) and x.startswith("@") and x[1:] in files else x for x in inputs]
    res = client.predict(*args, api_name=a.api)
    print(json.dumps(res, indent=1, default=str))  # file outputs come back as local temp paths


if __name__ == "__main__":
    main()
