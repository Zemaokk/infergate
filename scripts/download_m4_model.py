"""Download the official Qwen ModelScope snapshot to the remote data volume."""

import json
import os
from pathlib import Path

from modelscope import snapshot_download

target = Path(os.environ.get(
    "M4_MODEL_PATH", "/root/shared-nvme/infergate-m4/models/Qwen2.5-7B-Instruct"
))
target.parent.mkdir(parents=True, exist_ok=True)
path = snapshot_download(
    "Qwen/Qwen2.5-7B-Instruct",
    revision=os.environ.get("M4_MODEL_REVISION", "master"),
    local_dir=str(target),
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.md", "LICENSE"],
    max_workers=4,
)
files = sorted(Path(path).glob("*.safetensors"))
if not files:
    raise RuntimeError("No model weights downloaded")
index = json.loads((Path(path) / "model.safetensors.index.json").read_text())
for name in set(index["weight_map"].values()):
    if not (Path(path) / name).is_file():
        raise RuntimeError(f"Missing model shard: {name}")
print(json.dumps({"model_path": path, "weight_bytes": sum(p.stat().st_size for p in files)}, indent=2))
