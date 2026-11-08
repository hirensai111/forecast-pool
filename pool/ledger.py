"""The Google Sheet ledger, plus an in-memory stand-in for tests and dry runs."""
import json

from . import config


def col_letter(n):
    """1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Ledger:
    """Common interface. Rows are lists in the tab's header order; records come back as dicts."""

    def headers(self, tab):
        return config.TABS[tab]

    def records(self, tab):
        values = self._values(tab)
        if not values:
            return []
        head = values[0]
        out = []
        for i, row in enumerate(values[1:], start=2):
            if not any(str(c).strip() for c in row):
                continue
            rec = {h: (row[j] if j < len(row) else "") for j, h in enumerate(head)}
            rec["_row"] = i
            out.append(rec)
        return out

    def update(self, tab, updates):
        """updates: list of (sheet_row, column_name, value)."""
        if not updates:
            return
        head = self.headers(tab)
        cells = [(r, head.index(c) + 1, v) for r, c, v in updates]
        self._write_cells(tab, cells)


class MemoryLedger(Ledger):
    def __init__(self):
        self.tabs = {t: [list(h)] for t, h in config.TABS.items()}

    def ensure_tabs(self):
        pass

    def _values(self, tab):
        return self.tabs[tab]

    def append(self, tab, rows):
        self.tabs[tab].extend([list(r) for r in rows])

    def _write_cells(self, tab, cells):
        rows = self.tabs[tab]
        for r, c, v in cells:
            while len(rows[r - 1]) < c:
                rows[r - 1].append("")
            rows[r - 1][c - 1] = v

    def replace(self, tab, rows):
        self.tabs[tab] = [list(config.TABS[tab])] + [list(r) for r in rows]


class SheetsLedger(Ledger):
    def __init__(self, sheet_id=None, service_account_json=None):
        import gspread  # imported here so tests run without it

        sheet_id = sheet_id or config.SHEET_ID
        creds = service_account_json or config.SERVICE_ACCOUNT_JSON
        if not sheet_id or not creds:
            raise SystemExit("Set POOL_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON first (see README).")
        gc = gspread.service_account_from_dict(json.loads(creds))
        self.sh = gc.open_by_key(sheet_id)
        self._ws = {}

    def ws(self, tab):
        if tab not in self._ws:
            self._ws[tab] = self.sh.worksheet(tab)
        return self._ws[tab]

    def ensure_tabs(self):
        """Create any missing tab and make sure row 1 holds the headers."""
        existing = {w.title: w for w in self.sh.worksheets()}
        for tab, head in config.TABS.items():
            w = existing.get(tab) or self.sh.add_worksheet(title=tab, rows=1000, cols=len(head) + 2)
            if w.row_values(1)[:len(head)] != head:
                w.update(range_name="A1", values=[head])
            w.freeze(rows=1)
            self._ws[tab] = w
        sheet1 = existing.get("Sheet1")
        if sheet1 is not None and len(self.sh.worksheets()) > 1 and not any(sheet1.get_all_values()):
            self.sh.del_worksheet(sheet1)

    def _values(self, tab):
        return self.ws(tab).get_all_values()

    def append(self, tab, rows):
        if rows:
            self.ws(tab).append_rows([list(r) for r in rows], value_input_option="RAW",
                                     table_range="A1")

    def _write_cells(self, tab, cells):
        data = [{"range": f"{col_letter(c)}{r}", "values": [[v]]} for r, c, v in cells]
        for i in range(0, len(data), 500):
            self.ws(tab).batch_update(data[i:i + 500], value_input_option="RAW")

    def replace(self, tab, rows):
        w = self.ws(tab)
        w.clear()
        w.update(range_name="A1", values=[list(config.TABS[tab])] + [list(r) for r in rows],
                 value_input_option="RAW")
