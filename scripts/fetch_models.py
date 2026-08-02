"""Download ASR models required for PyInstaller packaging.

Used by .github/workflows/release.yml on CI where models/ is not in the repo
(gitignored). Idempotent: skips files that already exist.

  sherpa:  k2-fsa/sherpa-onnx asr-models release (zh-14M streaming zipformer)
  whisper: Systran/faster-whisper-base from Hugging Face

Usage:
    python scripts/fetch_models.py
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

SHERPA_RELEASE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23.tar.bz2"
)
SHERPA_TARGET = MODELS_DIR / "sherpa-streaming-zh-14M"

WHISPER_FILES = (
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
)
WHISPER_TARGET = MODELS_DIR / "faster-whisper-base"
WHISPER_BASE = "https://huggingface.co/Systran/faster-whisper-base/resolve/main"

UA = {"User-Agent": "vocis-ci/1.0"}


def _download(url: str, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] downloading {url}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"[fetch] saved {dest} ({dest.stat().st_size} bytes)")


def fetch_sherpa() -> None:
    need = {
        name: path
        for name, path in (
            ("encoder-epoch-99-avg-1.int8.onnx", SHERPA_TARGET / "encoder-epoch-99-avg-1.int8.onnx"),
            ("decoder-epoch-99-avg-1.int8.onnx", SHERPA_TARGET / "decoder-epoch-99-avg-1.int8.onnx"),
            ("joiner-epoch-99-avg-1.int8.onnx", SHERPA_TARGET / "joiner-epoch-99-avg-1.int8.onnx"),
            ("tokens.txt", SHERPA_TARGET / "tokens.txt"),
        )
        if not path.exists()}
    if not need:
        print("[fetch] sherpa model already present")
        return
    tmp = MODELS_DIR / "_sherpa.tar.bz2"
    _download(SHERPA_RELEASE, tmp)
    SHERPA_TARGET.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tmp, "r:bz2") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = pathlib.PurePosixPath(member.name).name
            if name in need:
                src = tf.extractfile(member)
                if src is None:
                    continue
                with open(need[name], "wb") as out:
                    shutil.copyfileobj(src, out)
                print(f"[fetch] extracted {need[name]}")
                del need[name]
    tmp.unlink(missing_ok=True)
    if need:
        print(f"[fetch] WARNING: missing sherpa files: {sorted(need)}")
        sys.exit(1)


def fetch_whisper() -> None:
    missing = [f for f in WHISPER_FILES if not (WHISPER_TARGET / f).exists()]
    if not missing:
        print("[fetch] whisper model already present")
        return
    WHISPER_TARGET.mkdir(parents=True, exist_ok=True)
    for name in missing:
        _download(f"{WHISPER_BASE}/{name}", WHISPER_TARGET / name)


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    fetch_sherpa()
    fetch_whisper()


if __name__ == "__main__":
    main()
