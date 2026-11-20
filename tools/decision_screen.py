"""Compare the recorded decision, summary and verification plan across two revisions."""
import difflib
from html import escape
import json
from pathlib import Path
import strateg as S


def snapshot(project):
    from delivery import snapshot as fingerprints
    files = [project / "decisions.md"]
    for prefix in ("0-", "5-"):
        files.extend(sorted((project/"outputs").glob(prefix+"*.md")))
    return dict(project=project.name, versions=fingerprints(project),
                documents={p.relative_to(project).as_posix():p.read_text(encoding="utf-8-sig").splitlines()
                           for p in files if p.is_file()})


def render(before, after):
    if before["project"] != after["project"]:
        raise ValueError("Выберите две версии одного проекта")
    blocks = []
    for name in dict.fromkeys([*before["documents"], *after["documents"]]):
        old, new = [item["documents"].get(name, []) for item in (before, after)]
        rows = []
        for op, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if op != "equal":
                for_left, for_right = ("\n".join(old[a:b]), "\n".join(new[c:d]))
                rows.append(f"<tr><td>{escape(for_left) or '—'}</td><td>{escape(for_right) or '—'}</td></tr>")
        if rows:
            blocks.append(f"<h2>{escape(name)}</h2><table><tr><th>Было</th><th>Стало</th></tr>{''.join(rows)}</table>")
    inputs = sorted(k for k in before['versions'].keys() | after['versions'].keys()
                    if k.startswith(('materials/', 'analysis/')) and before['versions'].get(k)!=after['versions'].get(k))
    return """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Было → стало</title>
<style>*{box-sizing:border-box}body{margin:48px auto;padding:0 20px;max-width:1080px;color:#19343c;background:#faf9f4;font:17px/1.55 system-ui}h1{font:52px Georgia;margin-bottom:12px}h2{font-size:18px;margin-top:32px}table{table-layout:fixed;border-collapse:collapse;width:100%}th,td{width:50%;text-align:left;vertical-align:top;padding:14px;border:1px solid #c4d5ce;white-space:pre-line;overflow-wrap:anywhere}th{background:#204b47;color:white}td{background:white}td+td{background:#ecf6ee}li{overflow-wrap:anywhere}</style><main><h1>Было → стало</h1>""" + f"<p>{escape(before['project'])}</p>" + ("".join(blocks) or "<p>Решение, сводка и план совпадают.</p>") + ("<h2>Обновлённые материалы и расчёты</h2><ul>"+''.join(f"<li>{escape(k)}</li>" for k in inputs)+"</ul>" if inputs else "")+"</main></html>"


def cmd(args):
    current = snapshot(S.project_dir(args.project))
    content = (json.dumps(current, ensure_ascii=False, indent=2) if args.action == 'checkpoint' else
               render(json.loads(Path(args.before).read_text(encoding='utf-8-sig')), current))
    with Path(args.output).open('x', encoding='utf-8') as out:
        out.write(content)
