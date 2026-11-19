"use strict";
// The duel between the two alliances of a week table, worked out for the week panel (the details page's top and the overview)
// (no DOM: tests/test_compare.py runs it in Node). `data` is a week table of the API (`aggregate.week_table`).
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat"];
const WIN_POINTS = { mon: 1, tue: 2, wed: 2, thu: 2, fri: 2, sat: 4 };   // what winning a day gives
const WIN_SCORE = 7;   // the points that win the duel (of the 13 there are)

const sum = (values) => values.reduce((a, b) => a + b, 0);
function median(values) {
  const sorted = values.slice().sort((a, b) => a - b), middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// The two alliances with the most points, the own one first: { alliance, tag, players, mine, members, zero (members with
// 0 points in total), total, average, median (per member) }. Every player of the table counts. Fewer than two without
// a second alliance.
function compareSides(data) {
  const groups = new Map();
  for (const player of data.players) {
    if (!player.alliance) continue;
    const key = [player.alliance, player.tag].join("|");
    if (!groups.has(key)) groups.set(key, { alliance: player.alliance, tag: player.tag, players: [], mine: player.alliance === data.my_alliance && player.tag === data.my_tag });
    groups.get(key).players.push(player);
  }
  return [...groups.values()]
    .map((group) => {
      const totals = group.players.map((player) => player.total);
      // the other alliance's members that are not in any list have 0 points: the count the week file knows of them
      const unseen = !group.mine && data.my_alliance ? Math.max(0, (data.opponent_members || 0) - totals.length) : 0;
      totals.push(...Array(unseen).fill(0));
      return { ...group, members: totals.length, zero: totals.filter((points) => points === 0).length, total: sum(totals), average: Math.round(sum(totals) / totals.length), median: Math.round(median(totals)) };
    })
    .sort((a, b) => b.mine - a.mine || b.total - a.total)
    .slice(0, 2);
}

// The days of the duel: { days: [{ day, points: [first, second], winner }], won: [first, second], winner }. `winner` of a
// day is 0 / 1, or -1 (not finished, no points yet, or a draw); `won` is the points of the days each side won; the
// duel's `winner` is the side that reached WIN_SCORE, else -1.
function duelDays(data, sides) {
  const won = [0, 0];
  const days = DAYS.map((day) => {   // every weekday has an entry; a day without data yet has no points
    const points = data.days.includes(day) ? sides.map((side) => sum(side.players.map((player) => player.points[day] || 0))) : [0, 0];
    const winner = points[0] + points[1] > 0 && data.final[day] && points[0] !== points[1] ? (points[0] > points[1] ? 0 : 1) : -1;
    if (winner >= 0) won[winner] += WIN_POINTS[day];
    return { day, points, winner };
  });
  return { days, won, winner: won.findIndex((points) => points >= WIN_SCORE) };
}

if (typeof module !== "undefined") module.exports = { DAYS, WIN_POINTS, WIN_SCORE, sum, median, compareSides, duelDays };
