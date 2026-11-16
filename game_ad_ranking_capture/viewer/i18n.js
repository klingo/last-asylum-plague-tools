"use strict";
// The viewer's languages and the pure helpers around them (no DOM: tests/test_i18n.py runs them in Node).
// A language is a file i18n/<code>.json; English is the one every other falls back to.
const LANGUAGES = [["en", "English"], ["de", "Deutsch"], ["ru", "Русский"]];

// The language to start in: a saved choice, else the first browser language that is supported, else English.
function pickLanguage(saved, preferred) {
  const codes = LANGUAGES.map(([code]) => code);
  if (codes.includes(saved)) return saved;
  for (const tag of preferred || []) {
    const base = String(tag).toLowerCase().split("-")[0];   // "de-CH" -> "de"
    if (codes.includes(base)) return base;
  }
  return "en";
}

// dict["info"]["players"] for "info.players"
function lookup(dict, key) {
  return key.split(".").reduce((node, part) => (node !== null && typeof node === "object" ? node[part] : undefined), dict);
}

// The text for a key in a language (English where the language lacks it, the key itself where English does too, so a
// missing text is seen). A text that is an object has plural forms (one / few / many / other), chosen by vars.n. The
// {name} placeholders are filled from vars.
function translate(dicts, lang, key, vars = {}) {
  let text = lookup(dicts[lang], key);
  if (text === undefined) text = lookup(dicts.en, key);
  if (text !== null && typeof text === "object") {
    const form = new Intl.PluralRules(lang).select(vars.n);
    text = text[form] !== undefined ? text[form] : text.other;
  }
  if (typeof text !== "string") return key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

if (typeof module !== "undefined") module.exports = { LANGUAGES, pickLanguage, lookup, translate };
