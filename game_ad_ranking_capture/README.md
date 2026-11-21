# Game AD Ranking Capture

Reads the **Alliance Duel** daily ranking of *Last Asylum: Plague* from BlueStacks (ADB screenshots + OCR), stores it as
one file per calendar week and shows it in a local browser page: points per day, total and average per player,
with a "My alliance" filter. A local helper; nothing is sent anywhere. Its only input to the game is taps and swipes.

## Use

Double-click **`start_gui.bat`**: it creates `.venv` if missing, runs `pip install -r requirements.txt` on every start
(offline it warns and goes on) and opens the window. The first scan downloads the OCR models (about 30 MB).

In the window:

1. **Checks** run when it opens (adb, device, game, the screen the game shows): everything should say OK. BlueStacks needs
   *Settings > Advanced > Android Debug Bridge* switched on and the game running.
2. **Scan** opens the Rank screen by itself (from the map, or from wherever the game is) and reads every ticked day that has
   data. **Do not touch the emulator while it runs.** One day with 160 players takes about 3.5 minutes. **Stop** ends it
   after the current page; days already read stay.
3. **Scan alliance members** reads the alliance's member list (Alliance > Alliance Members) for the zero-point days, see
   below. Run it when someone joined or left, not every day.
4. **Open rankings in browser** shows the weekly files. **Open data folder** opens `data/`.

Command line (from this folder): `.venv/Scripts/python main.py check | capture [--days mon,tue] [--force] | members [--since DATE] | status | view`.

## How it works

- **Navigation** (`screens.py`): every screen is recognised by its text; the Duel's icon on the map (no text) by matching
  `templates/duel_icon.png`. Each step is checked, an unknown screen is left with the on-screen back arrow (never the Android
  back key), and after a few of those it stops with a message instead of tapping around.
- **Servers**: the Duel's **Details** tab shows both alliances' server numbers (`#127` for yours on the left, `#122` for the
  opponent on the right). A scan reads them once per week, before it opens the Rank screen, and keeps them in the week file's
  `meta` (`my_server`, `opponent_server`); a week that has them is not touched again (`--force` / "Read final days again"
  reads them again). It is best effort: a Sunday has no Duel (the tab may already show the next opponent), and a tab that
  cannot be read costs a message in the scan log, never the scan. The API tables (`aggregate.week_table`) carry both numbers.
- **Days**: Monday to Saturday (the Duel has no Sunday). A day tab the game does not switch to has **no data yet**.
  A day's numbers are **preliminary** until its game day has ended: the game's day changes at the 02:00 UTC reset (server
  time is UTC-2), i.e. 03:00 CET / 04:00 CEST, so Monday's list is final from Tuesday 03:00 CET on. A preliminary day is
  recorded (marked `final: false`, "preliminary" in the viewer) and read again by every scan. A day is **final** once a
  complete scan of it *started* after its game day ended (a scan that runs across the reset does not count); final days are
  skipped (`--force` / "Read final days again" reads them again), so a run only fills in missing and preliminary days.
- **Reading a list** (`scan.py`, `rows.py`): scroll to the top (fast swipes, several between two looks at the screen, nothing read on the way), read a page, swipe, repeat until two swipes bring nothing new
  (the list ends at the last player with points, at most 200). Pages are merged by rank. The swipe length is measured from
  where the same cards sit on two pages, so a skipped card is noticed and read again. Ranks 1-3 are medals: they get their
  rank from the card below. The points are the anchor of each row; name, alliance and rank are found around them.
  From about rank 105 on the game shows "Not ranked" instead of a number: those players are read all the same (name, alliance,
  points), placed by a card the earlier pages already read, and numbered by their position in the list, which is by points
  (highest first, the last one has the last rank).
- **OCR**: RapidOCR. Latin names and digits are read well; rows with an empty or unsure name are read again with a Cyrillic
  model. A name made of square symbols (`■□■`, the game's stand-in for characters its font lacks) is no text to any
  model: when both engines found no name, the name line is searched for solid and outlined squares (`symbols.py`). Anything
  still unreadable is stored as `?` and goes to the review list.

## Files

- `data/<year>-W<week>.json`: one calendar week (ISO), committed. `{week, start, meta: {my_name, my_alliance, my_tag, my_server, opponent_server},
  days: {mon: {date, captured_at, final, complete, rows: [{rank, name, alliance, tag, points}]}}}`, one row per line so a
  diff shows what changed. `complete: false` means the list was not read to its end.
- `corrections.json`: two sections, applied when the viewer builds its table. The weekly files keep the names as scanned,
  so an edit takes effect on the next reload, also for days that are final and never scanned again.
  - `"corrections"`: `"misread": "right"` replaces that text wherever it is a name, alliance or tag (the game's font makes
    `I` and `l` look the same: `"SolM": "SoIM"`); `"<week>/<day>/<rank>": "name"` sets the name of one card, e.g.
    `"2026-W47/mon/18": "Name"` for a name the OCR could not read (stored as `?`).
  - `"aliases"`: a player who **renamed**. `"OldName": "NewName"` makes every card named OldName, in every week, a card of
    NewName, so the days before and after the rename are one player in the table (total and average over all
    of them). Look-alike spellings of OldName match too, and renames can be chained (`"A": "B", "B": "C"`).
- `members/<year>-W<week>.json`: the alliance's member lists, one file per calendar week (see **Members** below).
- `review/<week>/<day>/rank-<n>.png` (git-ignored): pictures of the cards the OCR was unsure about, to check by eye.

## Members: the zero-point days

A member with 0 points on a day is not in the Duel's ranking, so the ranking alone cannot show who contributed nothing.
`members` (or the window's **Scan alliance members**) reads the alliance's member list, which is only needed when someone
joined or left, and the viewer then counts every member missing from a day's ranking as **0 points** for that day (in
italics, with a tooltip): the zeros are part of the average, the day gets the lowest colour. Players of other
alliances are not touched.

- The screen shows the leader pinned at the top and the other members as cards in two columns, **grouped by rank, each group
  foldable**. A folded group shows no cards: the scan reads every group header's arrow (up = folded) and opens the folded
  ones (they stay open in the game). The cards of a group must add up to the group's count and everything to the member
  count at the top of the screen; a list that does not add up is **not stored** (a wrong list would put wrong zeros in the
  table).
- This screen only takes a drag that starts on a card: a swipe that starts on a rank header or in the gap between two rows
  does nothing. A swipe that moved nothing is repeated from other start heights, and only counts as the end of the list when
  every one of them failed.
- **One file per calendar week**, like the points files: `data/members/<year>-W<week>.json` holds that week's lists
  `{since, scanned_at, total, members: [{name, rank}]}`. A list is valid from its `since` day (the game day it was read,
  or `--since YYYY-MM-DD` when the change is known to be older; the date can also be edited in the file) until the next one.
  Reading the list again on the same day replaces it, and the scan says who **joined or left** since the list before.
- **Which list a day uses**: the most recent list valid by that day, so a week without a list of its own uses the latest
  earlier one (you only read the list when someone joined or left) and a joiner counts from the list on, a leaver only up
  to it. If there is none, the earliest list of the same calendar week (a first list read on Wednesday also covers Monday
  and Tuesday); else the day has no member list and gets no zeros, so weeks before the first list stay as they are.
- The zeros are worked out when the table is built, never written into the weekly points files: a corrected or backfilled
  list changes the history at once.
- **The ranking tells when the list is out of date.** After each ranking scan, players of your alliance who are not in the
  list that applies are reported as probably joined, and listed members who appear under another alliance as probably left
  ("Read the member list again"): you do not have to remember to re-scan.
- **A joiner counts without a new list.** A player of your alliance who is in a day's ranking but not in that day's list is
  taken as a member from that day on (the days before are left empty: they were no member yet), so their later days
  without points get a zero as well. This holds for the week the table is built for; reading the list again makes it
  official (and gives the rank).
- Member names are matched like the ranking's names (look-alike characters, case, `corrections.json` and aliases), so a
  renamed member is one player. A member whose name could not be read (`?`) cannot be matched and is left out.

## Viewer

Week selector (newest first), **My alliance** (the alliance of your own pinned row), sortable columns. The **Rank** column
(R5 is the highest, sorted R5 first) is the member's alliance rank from the member list, so it is there for your own
alliance; players the lists do not know (other alliances) have none. A member who left keeps the last rank known. A player missing from
a day's list shows `-` and is left out of the average (not counted as 0). The same player read with `I` one day and
`l` another is one player. Days that are still preliminary are marked "preliminary" in orange (hover for the explanation). The info line under the table shows when the last scan was
taken, and hovering a day's heading shows when that day was scanned (both in the viewer's local time). On your own alliance's rows every daily cell has a small icon on the left
(`viewer/assets/`): `red.png` below phase 5, `green.png` from phase 9, `amber.png` in between (the first and last phase
of the colour scale in `config.py`).

Both pages have the same header (`viewer/base.css`): the title, the links to the overview and the details, and the language
selector. On the details page a bar below it has the week selector and the info line (preliminary days, last scan), and a bar
above the table the "My alliance" filter and the colour legend.

Above the table, a panel shows the week's duel (yours blue, the other red; the "My alliance" filter does not change
it), built by `viewer/week-panel.js` like the overview's rows. Left: the calendar week, its dates and "In progress" while a day
is not finished. In the middle the score: a won day gives points (Monday 1, Saturday 4, the other days 2), only finished days count,
yours first; whoever reaches 7 of the 13 points has won and gets `win.png` beside their tag. Right: the points of the week so
far with each one's share bar, the average and median per member and the members with 0 points (a member's total for the week; your
alliance counts its roster members with 0 points, the other the players the lists show, plus, if you enter
`"opponent_members": 100` in the week file's `meta` by hand, nameless members with 0 points up to that count). At the far
right (below the stats on a narrower window) the weekdays underneath each other, one share bar each (a day without data has no
bar; hover a bar for the two point totals), with `win.png` on the side of the winner of a finished day.

**Overview** (`index.html`, the start page; the "Overview" link in the details page's header): one panel per week, newest first: the
calendar week and its dates, the two alliances with the score of the duel (`win.png` beside the winner once it is decided,
"In progress" while a day is not finished), and their total points and average / median per member. A panel opens the
details page (`details.html?week=<week>`) with that week selected. The panel is the same as the details page's (`viewer/week-panel.js`, `week-panel.css`), without the days and the share bar; the numbers come from `viewer/compare.js`.

**Languages**: English, German and Russian. The page starts in the browser's language (the first of its preferred
languages that is supported, else English); a small selector in the top-right corner changes it and the choice is
remembered in the browser. The texts are in `viewer/i18n/en.json`, `de.json` and `ru.json` (English is the source and the
fallback for a missing text); `viewer/i18n.js` holds the language choice and the lookup. Numbers are written the same way
in every language (`20'000`), dates and plural forms (`1 игрок`, `2 игрока`, `5 игроков`) follow the language. The event's name
is translated: German (Allianz-Duell) is the game's own text; Russian (Дуэль альянсов) is not from the game, whose Russian texts
are not extracted, so correct it if the game words it differently.
A new language: its file in `viewer/i18n/`, an entry in `LANGUAGES` (`i18n.js`) and its plural forms in
`tests/test_i18n.py`; the test checks that every file has exactly the keys, placeholders and plural forms it needs, and that
the page uses no text that is not in the files.

**Colours**: the daily points and the Average are coloured by the Duel's 9 daily reward phases (`PHASES` in
`config.py`: 38'000, 145'000, 550'000, 650'000, 1'020'000, 2'280'000, 2'630'000, 3'620'000, 7'190'000). It is a scale, not
bands: **red** at phase 5 (1'020'000) and below, **amber** at phase 7 (2'630'000), **green** at phase 9 (7'190'000) and
above, blended in between (`COLOR_SCALE`; the legend in the header shows it). A cell's tooltip names the phase it
reaches. The Total is not coloured: it is not a day's points. If the game changes a phase's points, change `PHASES`.

## Publishing to GitHub Pages

`export.py` (`python export.py [--out DIR]`, default `site/`, git-ignored) writes the viewer as a static site: the pages (`index.html`, `details.html`) and their scripts,
`api/weeks.json` and one `api/week/<week>.json` table per week, with the corrections, aliases and member lists applied. It
needs nothing but Python (no OpenCV, no OCR). The page is the same as the local one: it fetches those files with relative
URLs, which are also the routes of the local server, so it works below `/<repository>/` too.

`.github/workflows/pages.yml` (repository root) builds and deploys it on **every push to `main`** (and by hand, "Run
workflow"), so the site always shows what was pushed last. One-time setup: *Settings > Pages > Build and deployment >
Source: GitHub Actions*. The site is at `https://<owner>.github.io/<repository>/`.

**It is public**: the tables hold the names of the players of both alliances. The page carries `noindex` (a request to search
engines, not a protection), and GitHub Pages of a private repository needs a plan that includes it and is still reachable by
anyone with the link unless the plan restricts access.

## Tests

`.venv/Scripts/python -m pytest -q`: small inline data, a fake game that scrolls a virtual list, and two real screenshots
(`tests/fixtures`) for the OCR; no game or device needed. The OCR tests skip themselves when the models cannot be loaded.
