# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss German benchmark: how well does the notetaker turn Swiss German speech
into Standard German? Uses the notetaker's own transcription and clean-up code
on samples with an official Standard German reference, and compares setups.

Samples, either:
  --parquet FILE   a Hugging Face parquet with audio + text, e.g. the open
                   SPC_R test set (i4ds/spc_r, CC BY 4.0)
  --folder DIR     your own clips: NAME.wav + NAME.txt (what was really said,
                   in Standard German); optional NAME.plaud.txt etc. are
                   scored as "other systems" for comparison

    MISTRAL_API_KEY=... python scripts/benchmark_swiss_german.py --parquet test.parquet --samples 40

Scores: WER (word error rate, lower is better) and BLEU (higher is better;
the usual score for Swiss German -> Standard German). Needs: jiwer, sacrebleu,
and pyarrow for --parquet.
"""

import argparse
import asyncio
import io
import json
import os
import random
import re
import sys
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from voxtral_notetaker.config import Language, NotetakerConfig  # noqa: E402
from voxtral_notetaker.transcription import VoxtralTranscriber  # noqa: E402
from voxtral_notetaker.dialect import clean_lines  # noqa: E402


@dataclass
class Setup:
    name: str
    model: str
    language: Language
    diarize: bool
    cleanup_model: str = ""  # "" = no dialect clean-up


SETUPS = {
    # What the device does today: speaker labels (language auto) + clean-up
    "small+speakers+cleanup": Setup("small+speakers+cleanup", "voxtral-small-transcribe-3-0",
                                    Language.AUTO, True, "mistral-medium-3-5"),
    "small+speakers": Setup("small+speakers", "voxtral-small-transcribe-3-0", Language.AUTO, True),
    "small+speakers+cleanup-small": Setup("small+speakers+cleanup-small",
                                          "voxtral-small-transcribe-3-0", Language.AUTO, True,
                                          "mistral-small-2603"),
    "small+de": Setup("small+de", "voxtral-small-transcribe-3-0", Language.DE, False),
    "small+de+cleanup": Setup("small+de+cleanup", "voxtral-small-transcribe-3-0", Language.DE,
                              False, "mistral-medium-3-5"),
    "mini+de": Setup("mini+de", "voxtral-mini-transcribe-3-0", Language.DE, False),
}


def normalize(text: str) -> str:
    """Compare words, not spelling details: lower case, ss for ß, no punctuation"""
    text = text.lower().replace("ß", "ss")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def load_parquet(path: str, count: int, seed: int, text_column: str = "text",
                 group_column: str = "", names_column: str = ""):
    """count samples at random; with group_column, count per group (e.g. per dialect)"""
    import pyarrow.parquet as pq
    columns = ["audio", text_column] + [c for c in (group_column, names_column) if c]
    rows = pq.read_table(path, columns=columns).to_pylist()
    random.Random(seed).shuffle(rows)
    if group_column:
        picked, per_group = [], {}
        for row in rows:
            group = row[group_column]
            if per_group.get(group, 0) < count:
                per_group[group] = per_group.get(group, 0) + 1
                picked.append(row)
        rows = sorted(picked, key=lambda r: r[group_column])
    else:
        rows = rows[:count]
    samples = []
    for i, row in enumerate(rows):
        samples.append({"id": f"s{i:03d}", "wav": to_wav(row["audio"]["bytes"]),
                        "reference": row[text_column], "others": {},
                        "group": row[group_column] if group_column else "",
                        "names": list(row[names_column] or []) if names_column else []})
    return samples


def load_folder(path: str):
    samples = []
    for name in sorted(os.listdir(path)):
        if not name.endswith(".wav"):
            continue
        stem = name[:-4]
        reference = os.path.join(path, stem + ".txt")
        if not os.path.exists(reference):
            print(f"skip {name}: no {stem}.txt with the reference text")
            continue
        others = {}
        for other in os.listdir(path):
            match = re.fullmatch(re.escape(stem) + r"\.(\w+)\.txt", other)
            if match:
                others[match.group(1)] = open(os.path.join(path, other), encoding="utf-8").read()
        samples.append({"id": stem, "wav": to_wav(open(os.path.join(path, name), "rb").read()),
                        "reference": open(reference, encoding="utf-8").read(), "others": others})
    return samples


def to_wav(data: bytes) -> bytes:
    """Samples come as MP3/FLAC too: convert to 16 kHz mono WAV, as the device records"""
    if data[:4] == b"RIFF":
        return data
    import subprocess
    # Into a real file: a WAV piped to stdout has no valid length in its header
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "s.wav")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1",
                        "-ar", "16000", out], input=data, capture_output=True, check=True)
        with open(out, "rb") as f:
            return f.read()


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wf:
        return wf.getnframes() / float(wf.getframerate())


def run_setup(setup: Setup, sample: dict, config: NotetakerConfig) -> str:
    vox = NotetakerConfig.from_dict(config.to_dict()).voxtral
    vox.model = setup.model
    transcriber = VoxtralTranscriber(vox)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(sample["wav"])
        path = f.name
    try:
        result = asyncio.run(transcriber.transcribe(path, setup.language, diarize=setup.diarize))
    finally:
        os.remove(path)
    lines = [s.text for s in result.segments if s.text] or [result.text]
    if setup.cleanup_model:
        cfg = NotetakerConfig.from_dict(config.to_dict())
        cfg.voxtral.dialect_model = setup.cleanup_model
        lines = clean_lines(lines, cfg)
    return " ".join(lines).strip()


def names_found(hypotheses, samples):
    """Share of expected names (e.g. place names) that appear in the output"""
    total = found = 0
    for hyp, sample in zip(hypotheses, samples):
        words = f" {normalize(hyp)} "
        for name in sample.get("names", []):
            total += 1
            found += f" {normalize(name)} " in words
    return 100.0 * found / total if total else None


def score(hypotheses, references):
    import jiwer
    import sacrebleu
    refs = [normalize(r) for r in references]
    hyps = [normalize(h) for h in hypotheses]
    wer = jiwer.wer(refs, hyps) if any(refs) else float("nan")
    bleu = sacrebleu.corpus_bleu(hyps, [refs]).score
    return wer * 100, bleu


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--parquet")
    parser.add_argument("--text-column", default="text",
                        help="column with the Standard German reference")
    parser.add_argument("--group-column", default="",
                        help="score per group (e.g. dialect_code); --samples is then per group")
    parser.add_argument("--names-column", default="",
                        help="column with names that must appear (e.g. cities_filled_de)")
    parser.add_argument("--folder")
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--setups", default=",".join(SETUPS),
                        help="comma-separated, from: " + ", ".join(SETUPS))
    parser.add_argument("--out", default="benchmark-results")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if not os.environ.get("MISTRAL_API_KEY"):
        print("Set MISTRAL_API_KEY", file=sys.stderr)
        return 1
    if bool(args.parquet) == bool(args.folder):
        print("Give either --parquet or --folder", file=sys.stderr)
        return 1
    samples = (load_parquet(args.parquet, args.samples, args.seed, args.text_column,
                            args.group_column, args.names_column) if args.parquet
               else load_folder(args.folder))
    if not samples:
        print("No samples", file=sys.stderr)
        return 1
    setups = [SETUPS[name.strip()] for name in args.setups.split(",") if name.strip()]
    config = NotetakerConfig()
    config.service.language = "de-CH"
    minutes = sum(wav_seconds(s["wav"]) for s in samples) / 60
    print(f"{len(samples)} samples, {minutes:.1f} min of audio, {len(setups)} setups\n")

    os.makedirs(args.out, exist_ok=True)
    results = {}
    for setup in setups:
        started = time.time()

        def one(sample, setup=setup):
            try:
                return run_setup(setup, sample, config)
            except Exception as e:  # keep going; an error counts as an empty transcript
                print(f"  {setup.name} {sample['id']}: {type(e).__name__}: {e}")
                return ""

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            hypotheses = list(pool.map(one, samples))
        wer, bleu = score(hypotheses, [s["reference"] for s in samples])
        names = names_found(hypotheses, samples)
        groups = {}
        for group in sorted({s["group"] for s in samples if s["group"]}):
            idx = [i for i, s in enumerate(samples) if s["group"] == group]
            groups[group] = score([hypotheses[i] for i in idx], [samples[i]["reference"] for i in idx])
        results[setup.name] = {"wer": wer, "bleu": bleu, "names": names, "groups": groups,
                               "seconds": time.time() - started, "hypotheses": hypotheses}
        extra = f"   names {names:5.1f} %" if names is not None else ""
        print(f"{setup.name:32s} WER {wer:5.1f} %   BLEU {bleu:5.1f}{extra}   "
              f"({time.time() - started:.0f} s)")
        if groups:
            print("    " + "  ".join(f"{g} {w:.0f}%" for g, (w, _) in groups.items()))

    other_names = sorted({name for s in samples for name in s["others"]})
    for name in other_names:
        picked = [s for s in samples if name in s["others"]]
        wer, bleu = score([s["others"][name] for s in picked], [s["reference"] for s in picked])
        results[f"other:{name}"] = {"wer": wer, "bleu": bleu, "samples": len(picked)}
        print(f"{'other: ' + name:32s} WER {wer:5.1f} %   BLEU {bleu:5.1f}   ({len(picked)} samples)")

    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"samples": [{"id": s["id"], "reference": s["reference"], "group": s["group"],
                                "names": s["names"]} for s in samples],
                   "results": results}, f, ensure_ascii=False, indent=1)
    print(f"\nDetails: {os.path.join(args.out, 'results.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
