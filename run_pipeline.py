#!/usr/bin/env python3
"""Main pipeline orchestrator.

Run:
    python run_pipeline.py                   # full data
    python run_pipeline.py --sample          # sample mode (not yet implemented as fixture)
    python run_pipeline.py --from sync       # resume from a specific step
    python run_pipeline.py --only pricing    # run only one step
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

import numpy as np

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.utils import load_config, project_root, save_manifest, setup_logging

logger = logging.getLogger("pipeline")

STEPS = [
    "specs",
    "ingest",
    "book",
    "clean",
    "session",
    "trades",
    "sync",
    "liquidity",
    "band_queue",
    "pricing",
    "axis_a",
    "axis_b",
    "report",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ahrom Options Research Pipeline")
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    p.add_argument("--from", dest="from_step", metavar="STEP", help="Resume from this step")
    p.add_argument("--only", metavar="STEP", help="Run only this step")
    p.add_argument("--sample", action="store_true", help="Enable sample_mode in config")
    p.add_argument("--instruments", nargs="*", help="Limit ingestion to these instrument IDs")
    return p.parse_args()


def run_step(name: str, cfg: dict, **kwargs) -> bool:
    """Run a single pipeline step. Returns True on success."""
    logger.info("=" * 60)
    logger.info("STEP: %s", name.upper())
    logger.info("=" * 60)

    try:
        if name == "specs":
            from src.specs import run
            run(cfg)

        elif name == "ingest":
            from src.ingest import run
            instr = kwargs.get("instrument_ids")
            run(cfg, instrument_ids=instr)

        elif name == "book":
            from src.book import run
            run(cfg)

        elif name == "clean":
            from src.clean import run
            run(cfg)

        elif name == "session":
            from src.session import run
            run(cfg)

        elif name == "trades":
            from src.trades import run
            run(cfg)

        elif name == "sync":
            from src.sync import run
            run(cfg)

        elif name == "liquidity":
            from src.liquidity import run
            run(cfg)

        elif name == "band_queue":
            from src.band_queue import run
            run(cfg)

        elif name == "pricing":
            from src.pricing import run
            run(cfg)

        elif name == "axis_a":
            from src.axis_a import run
            run(cfg)

        elif name == "axis_b":
            from src.axis_b import run
            run(cfg)

        elif name == "report":
            from src.report import run
            run(cfg)

        else:
            logger.error("Unknown step: %s", name)
            return False

        logger.info("STEP %s: OK", name.upper())
        return True

    except Exception as e:
        logger.exception("STEP %s FAILED: %s", name.upper(), e)
        return False


def main() -> None:
    setup_logging()
    args = parse_args()

    cfg = load_config(args.config)

    if args.sample:
        cfg["run"]["sample_mode"] = True
        logger.info("Sample mode enabled")

    # Seed for reproducibility
    seed = cfg["run"]["seed"]
    random.seed(seed)
    np.random.seed(seed)
    logger.info("Random seed: %d", seed)

    # Determine which steps to run
    if args.only:
        steps = [args.only]
        logger.info("Running only step: %s", args.only)
    elif args.from_step:
        if args.from_step not in STEPS:
            logger.error("Unknown --from step: %s. Valid steps: %s", args.from_step, STEPS)
            sys.exit(1)
        idx = STEPS.index(args.from_step)
        steps = STEPS[idx:]
        logger.info("Resuming from step: %s", args.from_step)
    else:
        steps = STEPS
        logger.info("Running full pipeline: %s", " → ".join(steps))

    # Record pipeline start in manifest
    import datetime
    save_manifest(cfg, {"pipeline_start": datetime.datetime.now().isoformat()})

    instrument_ids = args.instruments

    failed = []
    for step in steps:
        ok = run_step(step, cfg, instrument_ids=instrument_ids)
        if not ok:
            failed.append(step)
            logger.error("Aborting pipeline at step: %s", step)
            break

    if failed:
        logger.error("Pipeline FAILED at: %s", failed)
        save_manifest(cfg, {"pipeline_status": "FAILED", "failed_step": failed[0]})
        sys.exit(1)
    else:
        logger.info("Pipeline COMPLETE. Check outputs/RESULTS.md")
        save_manifest(
            cfg,
            {
                "pipeline_status": "SUCCESS",
                "steps_run": steps,
                "pipeline_end": datetime.datetime.now().isoformat(),
            },
        )


if __name__ == "__main__":
    main()
