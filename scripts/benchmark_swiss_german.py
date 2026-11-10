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
                                    Language.AUTO, True, "mistral-small-2603"),
    "small+speakers": Setup("small+speakers", "voxtral-small-transcribe-3-0", Language.AUTO, True),
    "small+de": Setup("small+de", "voxtral-small-transcribe-3-0", Language.DE, False),
    "small+de+cleanup": Setup("small+de+cleanup", "voxtral-small-transcribe-3-0", Language.DE,
                              False, "mistral-small-2603"),
    "small+speakers+cleanup-large": Setup("small+speakers+cleanup-large",
                                          "voxtral-small-transcribe-3-0", Language.AUTO, True,
                                          "mistral-large-4-0"),
    "mini+de": Setup("mini+de", "voxtral-mini-transcribe-3-0", Language.DE, False),
}


def normalize(text: str) -> str:
    """Compare words, not spelling details: lower case, ss for ß, no punctuation"""
    text = text.lower().replace("ß", "ss")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def load_parquet(path: str, count: int, seed: int):
    import pyarrow.parquet as pq
    table = pq.read_table(path, columns=["audio", "text"])
    rows = table.to_pylist()
    random.Random(seed).shuffle(rows)
    samples = []
    for i, row in enumerate(rows[:count]):
        samples.append({"id": f"spc_{i:03d}", "wav": row["audio"]["bytes"],
                        "reference": row["text"], "others": {}})
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
        samples.append({"id": stem, "wav": open(os.path.join(path, name), "rb").read(),
                        "reference": open(reference, encoding="utf-8").read(), "others": others})
    return samples


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
        cfg.summary.model = setup.cleanup_model
        lines = clean_lines(lines, cfg)
    return " ".join(lines).strip()


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
    samples = (load_parquet(args.parquet, args.samples, args.seed) if args.parquet
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
        results[setup.name] = {"wer": wer, "bleu": bleu, "seconds": time.time() - started,
                               "hypotheses": hypotheses}
        print(f"{setup.name:32s} WER {wer:5.1f} %   BLEU {bleu:5.1f}   ({time.time() - started:.0f} s)")

    other_names = sorted({name for s in samples for name in s["others"]})
    for name in other_names:
        picked = [s for s in samples if name in s["others"]]
        wer, bleu = score([s["others"][name] for s in picked], [s["reference"] for s in picked])
        results[f"other:{name}"] = {"wer": wer, "bleu": bleu, "samples": len(picked)}
        print(f"{'other: ' + name:32s} WER {wer:5.1f} %   BLEU {bleu:5.1f}   ({len(picked)} samples)")

    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"samples": [{"id": s["id"], "reference": s["reference"]} for s in samples],
                   "results": results}, f, ensure_ascii=False, indent=1)
    print(f"\nDetails: {os.path.join(args.out, 'results.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
