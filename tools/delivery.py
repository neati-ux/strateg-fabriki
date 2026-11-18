"""Review snapshots and reproducible handoff bundles."""
import hashlib
import json
import zipfile
from pathlib import Path

import extra
import strateg as S


def documents(project):
    return sorted((project / 'outputs').glob('*.md'))


def snapshot(project):
    paths = documents(project) + [project / name for name in (
        'decisions.md', 'gates.json', 'claims.csv', 'materials/sources.csv', 'revisions.json')]
    for directory in ('materials', 'analysis'):
        paths.extend((project / directory).rglob('*'))
    tracked = sorted({p for p in paths if p.is_file() and not p.is_symlink()
                      and '__pycache__' not in p.parts and p.suffix not in {'.tmp', '.pyc'}})
    result = {}
    for path in tracked:
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError('Материал выходит за границы проекта')
        digest = hashlib.sha256()
        with path.open('rb') as file:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
        result[path.relative_to(project).as_posix()] = digest.hexdigest()
    return result


def cmd(args):
    project = S.project_dir(args.project)
    paths = documents(project)
    if not paths:
        S.die('нет итоговых документов')
    errors, _ = S.run_check(project)
    if errors:
        S.die('исправьте ошибки команды check перед выпуском')
    _, claims = S.load(project)
    stale = {c['id'] for c in claims if c['статус'] in ('на пересмотре', 'отозвано')}
    active_docs = [p for p in paths if p.name[:2] in ('0-', '3-', '4-', '5-')]
    for path in active_docs:
        refs = stale & S.find_refs(path)
        if refs:
            S.die(f'{path.name}: проверь основания перед выпуском: {", ".join(sorted(refs))}')
    reviewed = project / 'delivery-review.json'
    current = snapshot(project)
    if args.action == 'review':
        temp = reviewed.with_suffix('.tmp')
        temp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        temp.replace(reviewed)
        print('Версии сверенных документов и оснований сохранены')
        return
    if not reviewed.is_file() or json.loads(reviewed.read_text(encoding='utf-8')) != current:
        S.die('документы или основания изменились: сверить их и выполнить delivery review')
    output = Path(args.output)
    if output.exists():
        S.die('выходной ZIP уже существует')
    extra.verify(project, run=False)
    report = extra.build_report(project)
    inputs = [project / name for name in ('claims.csv', 'decisions.md', 'materials/sources.csv')]
    analysis = project / 'analysis'
    calculations = sorted(p for p in analysis.iterdir() if p.is_file() and p.suffix in {'.py', '.csv', '.json', '.txt'}) if analysis.is_dir() else []
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in paths + [report, reviewed] + inputs + calculations:
            if path.is_file():
                bundle.write(path, path.relative_to(project).as_posix())
        bundle.writestr('START.md', '# Пакет для руководителя\n\nОткройте outputs/REPORT.html. Сводка и стратегии доступны в Markdown, реестр — в CSV. Расчёты, если подготовлены, находятся в analysis/. Оригиналы материалов хранятся в проекте.\n')
    print(output.resolve())


def register(sub):
    parser = sub.add_parser('delivery', help='зафиксировать сверку и собрать пакет руководителя')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('review', help='зафиксировать версию после содержательной сверки').set_defaults(fn=cmd)
    actions.add_parser('pack', help='собрать ZIP из сверенной версии').add_argument('--output', required=True)
    parser.set_defaults(fn=cmd)
