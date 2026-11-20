/**
 * Land Command Center: a small web API on the Google Sheet, so Claude and the scheduled
 * tasks can read and update it. Paste into the sheet: Extensions → Apps Script.
 *
 * Setup (once):
 *   1. Paste this file, save, then run  setup  (choose it in the function menu, press Run,
 *      allow access). It creates a random access token and shows it in the Execution log.
 *   2. Deploy → New deployment → type "Web app" → Execute as: Me → Who has access: Anyone →
 *      Deploy. Copy the Web app URL.
 *   3. Give Claude the URL and the token (see the setup message).
 *
 * Every request needs the token. It never deletes rows; "replace" is only allowed on the
 * tabs listed in REPLACEABLE (reports Claude writes from scratch, like Today).
 *
 * POST JSON body {token, action, tab, ...}:
 *   read     → {rows: [{header: value}, ...]}
 *   upsert   {key: "Lead ID", rows: [{...}]}  update matching rows (only the fields sent),
 *                                            append rows whose key is new
 *   append   {rows: [{...}]}                 add rows at the bottom
 *   replace  {headers: [...], rows: [[...]]} clear and rewrite a report tab (REPLACEABLE only)
 * GET ?token=...&action=read&tab=Pipeline works too.
 */
var REPLACEABLE = ['Today', 'Swipes'];

function setup() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('TOKEN');
  if (!token) {
    token = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '').slice(0, 8);
    props.setProperty('TOKEN', token);
  }
  Logger.log('Access token for Claude: ' + token);
  Logger.log('Next: Deploy → New deployment → Web app (Execute as: Me, Who has access: Anyone), then give Claude the URL and this token.');
}

function doGet(e) { return handle_(e.parameter || {}); }

function doPost(e) {
  var body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({error: 'Body is not JSON'}); }
  return handle_(body);
}

function handle_(req) {
  var token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || req.token !== token) return out_({error: 'Wrong or missing token'});
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var tab = String(req.tab || 'Pipeline');
    var sh = ss.getSheetByName(tab);
    if (req.action === 'tabs') return out_({tabs: ss.getSheets().map(function (s) { return s.getName(); })});
    if (!sh) {
      if (req.action === 'read') return out_({error: 'No tab named ' + tab});
      sh = ss.insertSheet(tab);
    }
    if (req.action === 'read') return out_({rows: readRows_(sh)});
    if (req.action === 'append') return out_(append_(sh, req.rows || []));
    if (req.action === 'upsert') return out_(upsert_(sh, String(req.key || 'Lead ID'), req.rows || []));
    if (req.action === 'replace') {
      if (REPLACEABLE.indexOf(tab) < 0) return out_({error: 'replace is only allowed on: ' + REPLACEABLE.join(', ')});
      sh.clearContents();
      var headers = req.headers || [], rows = req.rows || [];
      if (headers.length) sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      if (rows.length) sh.getRange(2, 1, rows.length, headers.length || rows[0].length).setValues(rows);
      return out_({ok: true, written: rows.length});
    }
    return out_({error: 'Unknown action ' + req.action});
  } finally {
    lock.releaseLock();
  }
}

function headers_(sh) {
  var lastCol = sh.getLastColumn();
  return lastCol ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String) : [];
}

function ensureHeaders_(sh, names) {
  var h = headers_(sh);
  names.forEach(function (n) {
    if (h.indexOf(n) < 0) { h.push(n); sh.getRange(1, h.length).setValue(n).setFontWeight('bold'); }
  });
  return h;
}

function readRows_(sh) {
  var v = sh.getDataRange().getValues();
  if (v.length < 2) return [];
  var h = v[0].map(String);
  return v.slice(1).filter(function (r) { return r.join('') !== ''; }).map(function (r) {
    var o = {}; h.forEach(function (k, i) { if (k) o[k] = r[i]; }); return o;
  });
}

function append_(sh, rows) {
  if (!rows.length) return {ok: true, appended: 0};
  var names = {}; rows.forEach(function (r) { Object.keys(r).forEach(function (k) { names[k] = 1; }); });
  var h = ensureHeaders_(sh, Object.keys(names));
  var values = rows.map(function (r) { return h.map(function (k) { return r[k] === undefined ? '' : r[k]; }); });
  sh.getRange(sh.getLastRow() + 1, 1, values.length, h.length).setValues(values);
  return {ok: true, appended: values.length};
}

function upsert_(sh, key, rows) {
  var names = {}; rows.forEach(function (r) { Object.keys(r).forEach(function (k) { names[k] = 1; }); });
  names[key] = 1;
  var h = ensureHeaders_(sh, Object.keys(names));
  var kc = h.indexOf(key);
  var last = sh.getLastRow();
  var keys = last > 1 ? sh.getRange(2, kc + 1, last - 1, 1).getValues().map(function (r) { return String(r[0]); }) : [];
  var updated = 0, fresh = [];
  rows.forEach(function (r) {
    var i = keys.indexOf(String(r[key]));
    if (i < 0) { fresh.push(r); return; }
    Object.keys(r).forEach(function (k) {
      if (k === key) return;
      sh.getRange(i + 2, h.indexOf(k) + 1).setValue(r[k]);
    });
    updated++;
  });
  var a = append_(sh, fresh);
  return {ok: true, updated: updated, appended: a.appended};
}

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
