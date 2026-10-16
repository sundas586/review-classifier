// Web app that lets the Review Classifier read and write tabs of a Google Sheet without a Google Cloud key.
// Deploy once: Extensions > Apps Script > paste this > Deploy > New deployment > Web app,
// "Execute as: Me", "Who has access: Anyone". Put the web app URL in APPS_SCRIPT_URL and TOKEN in APPS_SCRIPT_TOKEN.
var TOKEN = 'change-this-secret';

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    if (req.token !== TOKEN) return out({ ok: false, error: 'bad_token' });

    var book;
    try {
      book = SpreadsheetApp.openById(req.sheetId);
    } catch (err) {
      return out({ ok: false, error: 'no_access' });
    }
    var sheet = findTab(book, req.tab);

    if (req.action === 'read') {
      if (!sheet) return out({ ok: true, found: false, values: [] });
      return out({ ok: true, found: true, values: sheet.getDataRange().getDisplayValues() });
    }

    if (req.action === 'write') {
      if (!sheet) sheet = book.insertSheet(req.tab);
      sheet.clear();
      var rows = req.rows || [];
      if (rows.length) {
        var width = rows[0].length;
        if (sheet.getMaxRows() < rows.length) sheet.insertRowsAfter(sheet.getMaxRows(), rows.length - sheet.getMaxRows());
        if (sheet.getMaxColumns() < width) sheet.insertColumnsAfter(sheet.getMaxColumns(), width - sheet.getMaxColumns());
        var range = sheet.getRange(1, 1, rows.length, width);
        range.setNumberFormat('@'); // store as text so nothing is read as a formula
        range.setValues(rows);
        (req.boldRows || []).forEach(function (r) {
          sheet.getRange(r, 1, 1, width).setFontWeight('bold');
        });
      }
      return out({ ok: true });
    }

    return out({ ok: false, error: 'unknown_action' });
  } catch (err) {
    return out({ ok: false, error: 'script_error', message: String(err) });
  }
}

function findTab(book, name) {
  var wanted = String(name).trim().toLowerCase();
  var sheets = book.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getName().trim().toLowerCase() === wanted) return sheets[i];
  }
  return null;
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
