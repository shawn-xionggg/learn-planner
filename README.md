# LEARN Planner

A local dashboard for Waterloo LEARN: upcoming deadlines, progress tracking, and searchable course-material links. Sign in through WatIAM and Duo, run the exporter, and open the generated HTML in your browser. No hosted server or database is required.

## Features

- **Upcoming deadlines:** show the next 30 days or a 7-day window. Past and undated items are hidden; finals and projects follow the same date rules.
- **Progress tracking:** mark items Done or Submitted; use Undo to restore them. Linked assignment/quiz calendar entries share progress.
- **Difficulty sorting:** hardest first, easiest first, or deadline order. Initial title/type estimates are editable.
- **Study-material search:** search course names, titles, nested module paths, and available descriptions. Includes resource links and an Open in LEARN fallback.
- **Local exports:** HTML dashboards, assignment CSV/JSON, and an unfiltered JSON snapshot.
- **Coverage reporting:** inaccessible sources and recurrence issues are reported explicitly.

## Quick start

Requires Python 3.10+, internet access, and a Waterloo LEARN account.

From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe learn_export.py --login
```

Complete WatIAM and Duo in the browser window. Then open:

- `exports/learn.html` — assignments, deadlines, and progress controls.
- `exports/study-materials.html` — searchable course resources.

On macOS/Linux, substitute `.venv/bin/python` for `.\.venv\Scripts\python.exe`.

## Refresh and customize

```powershell
# Refresh the 30-day planner and study-material index
.\.venv\Scripts\python.exe learn_export.py

# Show only the next week
.\.venv\Scripts\python.exe learn_export.py --days 7

# Renew an expired login
.\.venv\Scripts\python.exe learn_export.py --login

# Restrict collection to selected course IDs
.\.venv\Scripts\python.exe learn_export.py --course 123456 --course 789012

# Change display timezone or output directory
.\.venv\Scripts\python.exe learn_export.py --timezone America/Toronto --output exports
```

Rerun the exporter and refresh the HTML page to advance the date window. Static reports do not refresh themselves. Study materials are not filtered by deadline.

## Using the planner

The dashboard starts with **To do** items sorted **Hardest first**. To restore a completed item, change **Show** to **Done**, **Submitted**, or **Everything**, then click **Undo**.

Progress and difficulty ratings are saved in browser local storage. Use the same browser and report location to retain them across exports. Clearing browser data removes these choices; IDE previews and browser settings may restrict persistence.

**Submitted only tracks progress locally. It does not submit work to LEARN.** These controls do not change CSV/JSON exports.

## Export files

| File | Contents |
| --- | --- |
| `learn.html` | Filtered interactive planner |
| `learn.csv` | Filtered spreadsheet export |
| `learn.json` | Filtered records and coverage |
| `learn-all.json` | Full assignment, quiz, and calendar snapshot |
| `study-materials.html` | Searchable course-content links |
| `study-materials.json` | Course-content metadata and links |

HTML dates use Toronto time by default. JSON/CSV preserve API date values. Passed timed deadlines are excluded at export time; all-day items remain through their calendar day. All-day end dates are exclusive. Assignment/quiz closing dates substitute for missing due dates.

## Coverage and limitations

The exporter reads Brightspace APIs through your authenticated browser session. It discovers API versions, follows pagination, traverses nested course content, and expands recurring events when supported.

- Only data available to your account is collected. Older enrollments may also appear.
- Deadlines mentioned only in PDFs, announcements, or external tools are not extracted.
- Study search indexes metadata, not text inside PDFs or external sites. It does not crawl links inside every document.
- Assignment and calendar records may both represent the same work; exact repeats are removed.
- Difficulty is a rough editable estimate, not an instructor-provided rating.
- Resource links may require a LEARN login in your normal browser.

Check report coverage warnings before relying on the list. Exit code `2` means exports were produced with warnings. Renew an expired session with `--login`.

## Privacy

The login session is stored in `.auth/waterloo.json`. It grants signed-in access: do not share it. Exports contain personal course information and should also stay private.

Git ignores authentication, exports, virtual environments, caches, and scratch files. If you choose a custom export folder, exclude it from Git before committing. The application reads LEARN data; it does not modify coursework or send exports to a hosted service.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

Tests cover pagination, failure reporting, date windows, safe HTML/CSV output, nested content, and resource links. Live integration requires a LEARN account.

| Source | Responsibility |
| --- | --- |
| `learn_export.py` | Login, API requests, filtering, planner exports |
| `study_materials.py` | Course-content indexing and resource page |
| `test_learn_export.py` | Planner/export tests |
| `test_study_materials.py` | Content indexing tests |

Built against the [Brightspace API documentation](https://docs.valence.desire2learn.com/reference.html). Independent project; not an official University of Waterloo or D2L product.
