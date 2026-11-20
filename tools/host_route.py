"""Run a model handoff and cross-check every completed message with the host."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from opencode_usage import receipt


def verify(events, database, provider, model):
    usage = receipt(events)
    ids = {event["part"]["messageID"] for line in events.read_text(encoding="utf-8-sig").splitlines()
           if line.strip() and (event := json.loads(line)).get("type") == "step_finish"}
    calls = []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for message in sorted(ids):
            row = db.execute("""SELECT json_extract(data,'$.model.providerID'), json_extract(data,'$.model.id'),
                                json_extract(data,'$.time.created'),json_extract(data,'$.time.completed'),json_extract(data,'$.cost')
                                FROM session_message WHERE session_id=? AND id=? AND type='assistant'""",
                             (usage["opencode_session"], message)).fetchone()
            if not row or row[:2] != (provider, model):
                raise ValueError(f"Назначена {provider}/{model}, журнал хоста вернул {row}")
            start, end, cost = row[2:]
            calls.append(dict(message=message, seconds=(end-start)/1000 if isinstance(start,int) and isinstance(end,int) and end>=start else None, cost_usd=cost))
    return dict(usage, provider=provider, model=model, model_verified=True, calls=calls, verified_messages=len(ids))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--database", type=Path, default=Path.home()/".local/share/opencode/opencode.db")
    parser.add_argument("--cli", default="opencode")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    job = json.loads(args.handoff.read_text(encoding="utf-8-sig"))
    provider = job["provider"]
    model = job["model"].removeprefix(provider + "/")
    if not args.verify_only:
        with args.events.open("xb") as out:
            subprocess.run([args.cli, "run", "--standalone", "--model", provider + "/" + model,
                            "--format", "json", "--", job["prompt"]], stdout=out, check=True, timeout=180)
    print(json.dumps(verify(args.events, args.database, provider, model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
