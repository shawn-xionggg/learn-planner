"""Course content link index; no deadline filtering."""
import html
import json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

BASE = 'https://learn.uwaterloo.ca'


def collect_materials(client, courses, version):
    items, warnings = [], []
    for course in courses:
        print(f"Study materials: {course['Name']}", flush=True)
        try:
            toc = client.get(f"/d2l/api/le/{version}/{course['Id']}/content/toc")
            if not isinstance(toc, dict) or not isinstance(toc.get('Modules'), list):
                raise ValueError('Unexpected table of contents response')
            seen = set()

            def visit(node, path=''):
                for topic in node.get('Topics', []):
                    identifier = topic.get('TopicId', topic.get('Id'))
                    if identifier in seen:
                        continue
                    seen.add(identifier)
                    view = f"{BASE}/d2l/le/content/{course['Id']}/viewContent/{identifier}/View"
                    url = urljoin(BASE, topic.get('Url') or view)
                    if urlparse(url).scheme not in ('https', 'http'):
                        url = view
                    description = topic.get('Description') or ''
                    if isinstance(description, dict):
                        description = description.get('Text') or description.get('Html') or ''
                    items.append(dict(course=course['Name'], course_id=course['Id'],
                                      title=topic.get('Title') or 'Untitled', module=path,
                                      description=description, url=url, learn_url=view,
                                      topic_id=identifier, type=topic.get('Type'), raw=topic))
                for module in node.get('Modules', []):
                    visit(module, ' / '.join(filter(None, [path, module.get('Title') or 'Untitled'])))
            visit(toc)
        except (RuntimeError, ValueError) as exc:
            warnings.append(f"{course['Name']}: {exc}")
    return dict(generated_at=datetime.now(timezone.utc).isoformat(), items=items, warnings=warnings)


def export_materials(report, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'study-materials.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    esc = lambda value: html.escape(str(value), quote=True)
    rows = []
    for item in report['items']:
        rows.append(f"<tr data-course='{esc(item['course'])}'><td>{esc(item['course'])}</td><td>{esc(item['module'])}</td><td><a href='{esc(item['url'])}' target='_blank' rel='noopener'>{esc(item['title'])}</a><p>{esc(item['description'])}</p><a href='{esc(item['learn_url'])}' target='_blank' rel='noopener'>Open in LEARN</a></td></tr>")
    options = ''.join(f"<option>{esc(course)}</option>" for course in sorted({i['course'] for i in report['items']}))
    warnings = ''.join(f'<li>{esc(w)}</li>' for w in report['warnings'])
    document = """<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Study materials</title>
<style>body{font:16px system-ui;background:#f6f8fb;color:#18263c;margin:32px}input,select{padding:12px;margin:8px 8px 8px 0;max-width:95%}input{width:480px}table{border-collapse:collapse;background:white;width:100%}td,th{padding:14px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}a{color:#174baf}p{line-height:1.5}.scroll{overflow:auto}</style>
<a href='learn.html'>Assignments &amp; deadlines</a><h1>Study materials</h1><p>Search course names, module paths, titles and available descriptions. Links may require a LEARN login. File contents and external sites are not indexed.</p>"""
    document += f"<p>Collected {esc(report['generated_at'])} · {len(rows)} resources</p><ul>{warnings}</ul><input id='search' aria-label='Search materials' placeholder='Search for calculus, lecture, practice, slides…'><select id='course' aria-label='Course'><option value=''>All courses</option>{options}</select><p id='count'></p><div class='scroll'><table><thead><tr><th>Course</th><th>Module</th><th>Resource</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    document += r"""<script>const rows=[...document.querySelectorAll('tbody tr')];function filter(){const terms=document.querySelector('#search').value.toLowerCase().split(/\s+/).filter(Boolean),course=document.querySelector('#course').value;let count=0;for(const row of rows){row.hidden=(course&&row.dataset.course!==course)||!terms.every(t=>row.textContent.toLowerCase().includes(t));if(!row.hidden)count++}document.querySelector('#count').textContent=count+' resources shown'}document.querySelector('#search').addEventListener('input',filter);document.querySelector('#course').addEventListener('change',filter);filter();</script></html>"""
    (folder / 'study-materials.html').write_text(document, encoding='utf-8')
