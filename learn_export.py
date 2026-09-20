"""Export the signed-in user's Waterloo LEARN assignments and events locally."""
import argparse
import csv
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

BASE = "https://learn.uwaterloo.ca"
ROOT = Path(__file__).resolve().parent


class APIError(RuntimeError):
    pass


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    if isinstance(value, dict):
        value = value.get("Text") or value.get("Html") or ""
    parser = TextParser()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())


class Client:
    def __init__(self, page):
        self.page = page

    def get(self, path):
        url = urljoin(BASE, path)
        if urlparse(url).netloc != urlparse(BASE).netloc:
            raise APIError("Refusing an API pagination link outside LEARN")
        for attempt in range(4):
            result = self.page.evaluate("""async url => {
                const response = await fetch(url, {credentials: 'same-origin'});
                return {status: response.status, text: await response.text()};
            }""", url)
            status = result["status"]
            if status == 429 or status >= 500:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
            if status != 200:
                raise APIError(f"HTTP {status}: {urlparse(url).path}")
            try:
                return json.loads(result["text"])
            except ValueError:
                raise APIError("LEARN returned a non-JSON page; your login may have expired") from None
        raise APIError("Request retries exhausted")

    def listing(self, path):
        items, seen = [], set()
        while path:
            if path in seen:
                raise APIError("Repeated pagination link; results may be incomplete")
            seen.add(path)
            data = self.get(path)
            if isinstance(data, list):
                items.extend(data)
                break
            if not isinstance(data, dict):
                raise APIError("Unexpected list response")
            batch = data.get("Items", data.get("Objects"))
            if not isinstance(batch, list):
                raise APIError("Expected Items or Objects in list response")
            items.extend(batch)
            paging = data.get("PagingInfo") or {}
            if paging.get("HasMoreItems"):
                bookmark = paging.get("Bookmark")
                if bookmark is None:
                    raise APIError("Missing pagination bookmark")
                from urllib.parse import parse_qsl, urlsplit, urlunsplit
                parts = urlsplit(path)
                params = dict(parse_qsl(parts.query))
                params["bookmark"] = bookmark
                path = urlunsplit(parts._replace(query=urlencode(params)))
            else:
                path = data.get("Next")
        return items


def normalize(kind, course, data):
    event = kind == "Event"
    identifier = data.get("CalendarEventId") if event else data.get("Id", data.get("QuizId"))
    association = data.get("AssociatedEntity") or {}
    link = data.get("CalendarEventViewUrl") or association.get("Link")
    if not link:
        link = f"/d2l/home/{course['Id']}"
    link = urljoin(BASE, link)
    if urlparse(link).scheme not in ("https", "http"):
        link = f"{BASE}/d2l/home/{course['Id']}"
    return {
        "course": course["Name"], "course_id": course["Id"],
        "kind": kind, "id": identifier,
        "title": data.get("Title") or data.get("Name") or "Untitled",
        "due": data.get("DueDate"),
        "start": (data.get("StartDateTime") or data.get("StartDay")) if event else data.get("StartDate"),
        "end": (data.get("EndDateTime") or data.get("EndDay")) if event else data.get("EndDate"),
        "all_day": bool(data.get("IsAllDayEvent")),
        "points": data.get("TotalPoints"),
        "description": plain(data.get("CustomInstructions") or data.get("Description") or data.get("Instructions")),
        "location": data.get("LocationName") or "",
        "event_type": data.get("EventType"),
        "associated_type": association.get("AssociatedEntityType"),
        "associated_id": association.get("AssociatedEntityId"),
        "recurring": bool(data.get("IsRecurring")), "url": link,
        "raw": data,
    }


def collect(client, args):
    versions = client.get("/d2l/api/versions/")
    if not isinstance(versions, list):
        raise APIError("Cannot discover supported API versions")
    version = {v["ProductCode"].lower(): v.get("LatestVersion") or v.get("Version") for v in versions}
    lp, le = args.lp_version or version.get("lp"), args.le_version or version.get("le")
    if not lp or not le:
        raise APIError("LP/LE version discovery failed; use --lp-version and --le-version")
    enrollments = client.listing(f"/d2l/api/lp/{lp}/enrollments/myenrollments/")
    courses = [e["OrgUnit"] for e in enrollments if (e.get("OrgUnit", {}).get("Type") or {}).get("Code") == "Course Offering"]
    if args.course:
        courses = [c for c in courses if str(c["Id"]) in args.course]
        missing = set(args.course) - {str(c["Id"]) for c in courses}
        if missing:
            raise APIError(f"Course IDs not found in your enrollments: {', '.join(sorted(missing))}")
    rows, warnings, coverage = [], [], []
    for course in courses:
        print(f"Collecting: {course['Name']}", flush=True)
        prefix = f"/d2l/api/le/{le}/{course['Id']}"
        for kind, suffix in [("Assignment", "dropbox/folders/"), ("Quiz", "quizzes/"), ("Event", "calendar/events/")]:
            status = {"course": course["Name"], "source": kind}
            try:
                records = client.listing(f"{prefix}/{suffix}")
                expanded = []
                for record in records:
                    if kind == "Event" and record.get("IsRecurring"):
                        if tuple(map(int, le.split('.'))) >= (1, 94):
                            try:
                                info = client.get(f"{prefix}/calendar/event/{record['CalendarEventId']}/occurrences")
                                occurrences = info.get("Occurrences")
                                if not isinstance(occurrences, list) or not occurrences:
                                    raise APIError("No recurrence occurrences returned")
                                expanded.extend([{**record, **o, "CalendarEventId": record['CalendarEventId']} for o in occurrences])
                                continue
                            except APIError as exc:
                                warnings.append(f"{course['Name']}: recurrence {record.get('Title')}: {exc}")
                        else:
                            warnings.append(f"{course['Name']}: recurring event '{record.get('Title')}' shown as series only (older API)")
                    expanded.append(record)
                rows.extend(normalize(kind, course, r) for r in expanded)
                status.update(status="ok", count=len(expanded))
            except APIError as exc:
                warnings.append(f"{course['Name']} / {kind}: {exc}")
                status.update(status="failed", count=0)
            coverage.append(status)
    if not courses:
        warnings.append("No course enrollments were returned.")
    # Remove exact repeats, retaining separate calendar availability/deadline events.
    unique = {}
    for row in rows:
        key = (row['course_id'], row['kind'], row['id'], row['start'], row['end'])
        unique[key] = row
    rows = sorted(unique.values(), key=lambda r: (r['due'] or r['start'] or r['end'] or '9999', r['course'], r['title']))
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "versions": {"lp": lp, "le": le},
            "courses": courses, "coverage": coverage, "warnings": warnings, "items": rows}


def upcoming_items(items, tz_name, now=None, days=30):
    """Only dated deadlines/assessments within the selected upcoming window."""
    tz = ZoneInfo(tz_name)
    current = (now or datetime.now(tz)).astimezone(tz)
    today = current.date()
    until = today + timedelta(days=days)
    selected = []
    for row in items:
        title = row.get('title', '')
        major = bool(re.search(r'\b(finals?|mid[ -]?terms?|exams?|examinations?|capstone)\b', title, re.I))
        # Practice resources are not major assessments merely because they mention an exam.
        major = major and not re.search(r'\b(practice|sample|review|preparation)\b', title, re.I)
        deadline = row.get('due')
        if row['kind'] == 'Event':
            if row.get('event_type') in (2, 4):
                continue  # Opening/unlock dates are not deadlines.
            is_deadline = row.get('event_type') in (3, 5, 6) or re.search(r'\b(due|deadline|closes?|ends?|last day)\b', title, re.I)
            deadline = deadline or (row.get('start') if is_deadline or major else None)
        else:
            deadline = deadline or row.get('end')
        value = deadline or (row.get('start') if major else None)
        date = None
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                date = parsed.astimezone(tz).date() if parsed.tzinfo else parsed.date()
                if not row.get('all_day') and len(value) > 10:
                    instant = parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
                    if instant <= current:
                        continue
            except ValueError:
                pass
        if date and date < today:
            continue
        if value and date and today <= date <= until:
            selected.append((date, row))
    selected.sort(key=lambda pair: (pair[0] is None, pair[0] or until, pair[1]['course'], pair[1]['title']))
    return [row for _, row in selected]


def export(report, folder, tz_name, now=None, days=30):
    folder.mkdir(parents=True, exist_ok=True)
    # Keep the full scrape separately so the view can be rebuilt without signing in.
    (folder / 'learn-all.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    report = {**report, 'items': upcoming_items(report['items'], tz_name, now, days)}
    tz = ZoneInfo(tz_name)
    def display(value, all_day=False):
        if not value:
            return "—"
        if all_day:
            return str(value)[:10] + " (all day)"
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return date.astimezone(tz).strftime("%Y-%m-%d %I:%M %p %Z") if date.tzinfo else value
        except ValueError:
            return value
    (folder / "learn.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = ["course", "kind", "title", "due", "start", "end", "all_day", "points", "description", "location", "url", "course_id", "id", "associated_type", "associated_id", "event_type", "recurring"]
    with (folder / "learn.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in report['items']:
            # Prevent spreadsheet interpretation of untrusted course text as formulas.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for k, v in row.items()})
    esc = lambda value: html.escape(str(value if value is not None else ""), quote=True)
    body = []
    for index, r in enumerate(report["items"]):
        details = esc(r['description'])
        if r['location']:
            details += "<p>Location: " + esc(r['location']) + "</p>"
        if r['recurring']:
            details += "<p>Recurring event — consult LEARN for recurrence details.</p>"
        entity_kind = r['kind']
        entity_id = r['id']
        if r.get('associated_id') is not None:
            associated = r.get('associated_type') or ''
            if associated.endswith('.Dropbox'):
                entity_kind, entity_id = 'Assignment', r['associated_id']
            elif associated.endswith('.Quiz'):
                entity_kind, entity_id = 'Quiz', r['associated_id']
        key = json.dumps([r['course_id'], entity_kind, str(entity_id)])
        if entity_kind == 'Event':
            key = json.dumps([r['course_id'], entity_kind, str(entity_id), r['start']])
        difficulty = 3 if re.search(r'\b(final|exam|midterm|project|capstone)\b', r['title'], re.I) else (1 if r['kind'] == 'Quiz' else 2)
        controls = "<td><select class='difficulty' aria-label='Difficulty'><option value='1'>Easy</option><option value='2'>Medium</option><option value='3'>Hard</option></select><small class='estimate'></small></td><td><span class='status'></span><div><button data-status='done'>Done</button> <button data-status='submitted'>Submitted</button> <button data-status='todo'>Undo</button></div></td>"
        body.append(f"<tr data-key='{esc(key)}' data-order='{index}' data-difficulty='{difficulty}'><td>{esc(r['course'])}</td><td>{esc(r['kind'])}</td><td><a href='{esc(r['url'])}'>{esc(r['title'])}</a><details><summary>Details</summary>{details or 'No description provided.'}</details></td><td>{esc(display(r['due']))}</td><td>{esc(display(r['start'], r['all_day']))}</td><td>{esc(display(r['end'], r['all_day']))}</td><td>{esc(r['points'])}</td>{controls}</tr>")
    warnings = ''.join(f"<li>{esc(w)}</li>" for w in report['warnings'])
    coverage = ''.join(f"<li>{esc(c['course'])} — {esc(c['source'])}: {esc(c['status'])} ({c['count']})</li>" for c in report['coverage'])
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LEARN planner</title>
<style>body{font:15px system-ui;margin:32px;background:#f6f8fb;color:#18263c}h1{margin-bottom:8px}input{padding:12px;width:min(90%,600px);margin:16px 0}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}th{background:#e7edf7}a{color:#174baf}details{max-width:650px;margin-top:8px}summary{cursor:pointer}.warning{background:#fff0d0;padding:16px}.scroll{overflow:auto}</style>
<h1>LEARN assignments & events</h1>"""
    document += "<p><a href='study-materials.html'>Search study materials</a></p>"
    document += f"<p>{len(report['items'])} items across {len(report['courses'])} courses. Updated {esc(display(report['generated_at']))}. Times: {esc(tz_name)}.</p>"
    document += f"<p>Showing only deadlines and scheduled assessments in the next {days} days. Past and undated items are hidden, and finals/projects receive no exception. Quiz/assignment closing dates are used when no due date is available.</p>"
    if warnings:
        document += f"<div class='warning'><strong>Incomplete coverage / warnings</strong><ul>{warnings}</ul></div>"
    document += """<style>button,select{padding:8px;margin:3px;border:1px solid #adb9cb;border-radius:6px;background:white;color:#18263c}button{cursor:pointer}button[aria-pressed=true]{background:#174baf;color:white}small{display:block;color:#59677b}.status{font-weight:600}tr.completed{background:#eef6ef}.controls{display:flex;gap:16px;flex-wrap:wrap}</style>
<p>Mark your progress here; these buttons do not submit work to LEARN. Difficulty starts as a title/type estimate and can be changed. Choices are saved in this browser for this report location.</p>
<p id='save-warning' role='status'></p><div class='controls'><label>Order <select id='sort'><option value='hard'>Hardest first</option><option value='easy'>Easiest first</option><option value='date'>Deadline order</option></select></label><label>Show <select id='progress'><option value='todo'>To do</option><option value='all'>Everything</option><option value='done'>Done</option><option value='submitted'>Submitted</option></select></label></div>"""
    document += f"<details><summary>Collection coverage</summary><ul>{coverage}</ul></details><input id='search' aria-label='Search items' placeholder='Search course, title, type or description…'><p id='count'></p><div class='scroll'><table><thead><tr><th>Course</th><th>Type</th><th>Title / details</th><th>Due</th><th>Starts / opens</th><th>Ends / closes</th><th>Points</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    document = document.replace('<th>Points</th>', '<th>Points</th><th>Difficulty</th><th>Progress</th>')
    document += """<script>
const rows=[...document.querySelectorAll('tbody tr')], storageKey='learn-planner-progress-v1';
let saved={};
try {const value=JSON.parse(localStorage.getItem(storageKey)||'{}');if(value && typeof value==='object' && !Array.isArray(value))saved=value;}
catch(e){document.querySelector('#save-warning').textContent='Saved choices could not be loaded. Changes may not persist.';}
function save(){try{localStorage.setItem(storageKey,JSON.stringify(saved));}catch(e){document.querySelector('#save-warning').textContent='Browser storage is unavailable. Your changes only last until this page closes.';}}
function state(row){return saved[row.dataset.key]||{};}
function level(row){return Number(state(row).difficulty)||Number(row.dataset.difficulty);}
function render(){
 const q=document.querySelector('#search').value.toLowerCase(), progress=document.querySelector('#progress').value, sort=document.querySelector('#sort').value;
 rows.sort((a,b)=>(sort==='date'?0:(sort==='hard'?level(b)-level(a):level(a)-level(b))) || Number(a.dataset.order)-Number(b.dataset.order));
 let n=0;
 for(const row of rows){
  const s=state(row), status=['done','submitted'].includes(s.status)?s.status:'todo';
  row.querySelector('.difficulty').value=level(row);
  row.querySelector('.estimate').textContent=s.difficulty?'Your rating':'Estimated';
  row.querySelector('.status').textContent={todo:'To do',done:'Done',submitted:'Submitted'}[status];
  row.classList.toggle('completed',status!=='todo');
  for(const button of row.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.status===status));
  row.hidden=!row.textContent.toLowerCase().includes(q)||(progress!=='all'&&status!==progress);
  if(!row.hidden)n++;
  document.querySelector('tbody').appendChild(row);
 }
 document.querySelector('#count').textContent=n+' items shown';
}
for(const row of rows){
 for(const button of row.querySelectorAll('button'))button.addEventListener('click',()=>{saved[row.dataset.key]={...state(row),status:button.dataset.status};save();render();});
 row.querySelector('.difficulty').addEventListener('change',event=>{saved[row.dataset.key]={...state(row),difficulty:Number(event.target.value)};save();render();});
}
document.querySelector('#search').addEventListener('input',render);
for(const id of ['sort','progress'])document.getElementById(id).addEventListener('change',render);
render();</script></html>"""
    (folder / "learn.html").write_text(document, encoding="utf-8")
    return len(report['items'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--login', action='store_true', help='Open browser for WatIAM / Duo login')
    parser.add_argument('--course', action='append', help='Only this course ID; repeat for multiple courses')
    parser.add_argument('--output', type=Path, default=ROOT / 'exports')
    parser.add_argument('--timezone', default='America/Toronto')
    parser.add_argument('--days', type=int, choices=(7, 30), default=30, help='Upcoming window: 7 days or 30 days (default)')
    parser.add_argument('--lp-version')
    parser.add_argument('--le-version')
    args = parser.parse_args()
    ZoneInfo(args.timezone)
    from playwright.sync_api import sync_playwright
    auth = ROOT / '.auth' / 'waterloo.json'
    login = args.login or not auth.exists()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not login)
        try:
            context = browser.new_context(storage_state=str(auth) if auth.exists() and not args.login else None)
            page = context.new_page()
            page.goto(BASE + '/d2l/home', wait_until='domcontentloaded')
            if login:
                print('Complete WatIAM and Duo in the browser. Waiting up to 5 minutes for LEARN…', flush=True)
                page.wait_for_url(lambda url: url.startswith(BASE + '/d2l/home'), timeout=300000)
            elif not page.url.startswith(BASE + '/d2l/home'):
                raise APIError('Saved login expired. Run again with --login.')
            auth.parent.mkdir(exist_ok=True)
            context.storage_state(path=str(auth))
            report = collect(Client(page), args)
            count = export(report, args.output, args.timezone, days=args.days)
            from study_materials import collect_materials, export_materials
            materials = collect_materials(Client(page), report['courses'], report['versions']['le'])
            export_materials(materials, args.output)
            report['warnings'].extend(materials['warnings'])
            print(f"Indexed {len(materials['items'])} study resources: {args.output.resolve() / 'study-materials.html'}", flush=True)
            print(f"Exported {count} matching items: {args.output.resolve() / 'learn.html'}", flush=True)
            for warning in report['warnings']:
                print('WARNING: ' + warning)
            return 2 if report['warnings'] else 0
        finally:
            browser.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (APIError, ValueError) as exc:
        raise SystemExit(str(exc))
