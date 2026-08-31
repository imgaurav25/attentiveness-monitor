#!/usr/bin/env python3
"""
clear_db.py
------------
Standalone utility to clear the Attentiveness Monitor's stored data.
Run it from the project root (same folder as core/, backend/, desktop_app/).

Default (clears just the "history" -- the log + snapshot images):
    python clear_db.py
    python clear_db.py --yes            # skip the confirmation prompt

Also clear the registered student roster (face images, trained model, labels):
    python clear_db.py --roster

Also reset settings.json back to defaults:
    python clear_db.py --settings

Clear absolutely everything, no prompt:
    python clear_db.py --all --yes
"""

import argparse
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SNAPSHOTS_DIR = os.path.join(LOGS_DIR, "snapshots")
EXCEL_PATH = os.path.join(LOGS_DIR, "attentiveness_log.xlsx")
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
MODEL_PATH = os.path.join(BASE_DIR, "trained_model.yml")
LABELS_PATH = os.path.join(BASE_DIR, "labels.json")
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")


def clear_excel_log():
    if os.path.exists(EXCEL_PATH):
        os.remove(EXCEL_PATH)
        print(f"  deleted {os.path.relpath(EXCEL_PATH, BASE_DIR)}")
    else:
        print("  no Excel log found, nothing to delete")


def clear_snapshots():
    if os.path.isdir(SNAPSHOTS_DIR):
        count = 0
        for fname in os.listdir(SNAPSHOTS_DIR):
            if fname == ".gitkeep":
                continue
            fpath = os.path.join(SNAPSHOTS_DIR, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
                count += 1
        print(f"  deleted {count} snapshot file(s)")
    else:
        print("  no snapshots folder found, nothing to delete")


def clear_roster():
    if os.path.isdir(DATASET_DIR):
        shutil.rmtree(DATASET_DIR)
        print(f"  deleted {os.path.relpath(DATASET_DIR, BASE_DIR)}/")
    else:
        print("  no dataset folder found, nothing to delete")
    for path in (MODEL_PATH, LABELS_PATH):
        if os.path.exists(path):
            os.remove(path)
            print(f"  deleted {os.path.relpath(path, BASE_DIR)}")
        else:
            print(f"  {os.path.basename(path)} not found, nothing to delete")


def clear_settings():
    if os.path.exists(SETTINGS_PATH):
        os.remove(SETTINGS_PATH)
        print(f"  deleted {os.path.relpath(SETTINGS_PATH, BASE_DIR)} (defaults will be recreated on next run)")
    else:
        print("  no settings.json found, nothing to delete")


def main():
    parser = argparse.ArgumentParser(description="Clear stored data for the Attentiveness Monitor.")
    parser.add_argument("--roster", action="store_true",
                         help="Also clear registered students (dataset/, labels.json, trained_model.yml)")
    parser.add_argument("--settings", action="store_true",
                         help="Also reset settings.json to defaults")
    parser.add_argument("--all", action="store_true",
                         help="Clear everything: history + roster + settings")
    parser.add_argument("--yes", "-y", action="store_true",
                         help="Do not ask for confirmation")
    args = parser.parse_args()

    do_roster = args.roster or args.all
    do_settings = args.settings or args.all

    print("This will permanently delete:")
    print("  - The Excel attentiveness/unknown-person log")
    print("  - All saved snapshot images")
    if do_roster:
        print("  - The registered student roster (face images, trained model, labels)")
    if do_settings:
        print("  - Your saved settings (settings.json)")
    print()

    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was deleted.")
            sys.exit(0)

    print("\nClearing...")
    clear_excel_log()
    clear_snapshots()
    if do_roster:
        clear_roster()
    if do_settings:
        clear_settings()

    print("\nDone.")


if __name__ == "__main__":
    main()
