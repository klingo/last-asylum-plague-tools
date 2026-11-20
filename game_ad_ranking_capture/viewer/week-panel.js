"use strict";
// The week's duel as a panel: the overview's rows and the top of the details page (week-panel.css; needs i18n.js and
// compare.js loaded first). The calendar week and its dates, the two alliances with their server and the score of the duel
// (the win icon beside the winner, the lose icon beside the loser), and their points with what a member has on average and in the middle. `detailed` adds the share bar of the
// points, the members with 0 points and every day's bar; `link` makes the panel a link to the details of the week.

function add(parent, text, className, tag = "div") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function resultImage(name) {
  const img = document.createElement("img");
  img.src = "assets/" + name + ".png";   // relative: also works under /<repo>/ on GitHub Pages
  img.alt = "";
  return img;
}

// The bar that splits 100 % between two values (the share of each, rounded so that the two make 100); none without points.
function shareBar(values) {
  const both = values[0] + values[1];
  if (!both) return null;
  const first = Math.round((100 * values[0]) / both), shares = [first, 100 - first];
  const bar = document.createElement("div");
  bar.className = "bar";
  values.forEach((_, index) => { add(bar, shares[index] + "%", "s" + index, "span").style.width = shares[index] + "%"; });
  return bar;
}

// Monday to Saturday of the week, without a repeated month or year (Nov 16 - 21, 2026), in the order of the language
function dateRange(start, lang) {
  const from = new Date(start + "T12:00:00"), to = new Date(from);
  to.setDate(to.getDate() + DAYS.length - 1);
  return new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", year: "numeric" }).formatRange(from, to);
}

function weekPanel(data, { t, lang, detailed = false, link = false }) {
  const sides = compareSides(data);
  const panel = document.createElement(link ? "a" : "div");
  panel.className = "week" + (detailed ? " detailed" : "");
  if (link) panel.href = "details.html?week=" + encodeURIComponent(data.week);   // the details page selects this week
  const duel = sides.length === 2 ? duelDays(data, sides) : null;
  const when = add(panel, "", "when");
  add(when, t("duel.week", { n: Number(data.week.split("-W")[1]) }), "nr");
  add(when, dateRange(data.start, lang), "dates");
  const done = duel && DAYS.every((day) => data.days.includes(day) && data.final[day]);
  if (!done) add(when, t("duel.in_progress"), "live").title = t("duel.in_progress_title");
  if (!duel) return panel;
  const row = add(panel, "", "duel");
  row.title = t("compare.score_title", { first: WIN_POINTS.mon, last: WIN_POINTS.sat, other: WIN_POINTS.tue });
  const side = (index) => {
    const box = add(row, "", "side s" + index);   // the result's icon sits outside the names, whose fixed width keeps it as far from the score on both sides
    const text = add(box, "", "text");
    add(text, sides[index].tag || sides[index].alliance, "tag");
    if (sides[index].tag) add(text, sides[index].alliance, "name");
    const server = sides[index].mine ? data.my_server : data.opponent_server;   // read from the game's Details tab, once a week
    if (server) add(text, "#" + server, "server");
    if (duel.winner >= 0) box.insertBefore(resultImage(duel.winner === index ? "win" : "lose"), index === 0 ? text : null);
  };
  side(0);
  const score = add(row, "", "score");
  add(score, duel.won[0], "s0", "span");
  score.append(" : ");
  add(score, duel.won[1], "s1", "span");
  side(1);
  const stats = add(panel, "", "stats");
  add(stats, "", "label");
  sides.forEach((s, index) => add(stats, t("compare.members", { n: s.members }), "head s" + index));
  const bar = detailed && shareBar(sides.map((s) => s.total));
  if (bar) stats.appendChild(bar);
  const rows = [["total", t("compare.total")], ["average", t("compare.average")], ["median", t("compare.median")]];
  if (detailed) rows.push(["zero", t("compare.zero_members")]);
  for (const [key, label] of rows) {
    add(stats, label, "label");
    sides.forEach((s, index) => add(stats, fmt(s[key]), s[key] > sides[1 - index][key] ? "lead" : ""));   // the higher one is bold
  }
  if (detailed) {   // the days underneath each other, to compare them: the weekday, the share bar, the win / lose icons beside the sides
    const days = add(panel, "", "days");
    for (const { day, points, winner } of duel.days) {
      const dayBar = shareBar(points);
      if (dayBar) dayBar.title = t("compare.versus", { a: fmt(points[0]), b: fmt(points[1]) });
      add(days, t("weekday." + day), "label");
      sides.forEach((_, index) => {
        const cell = add(days, "", "win s" + index);
        if (winner >= 0) cell.appendChild(resultImage(index === winner ? "win" : "lose"));
        if (index === 0) days.appendChild(dayBar || document.createElement("div"));
      });
    }
  }
  return panel;
}
