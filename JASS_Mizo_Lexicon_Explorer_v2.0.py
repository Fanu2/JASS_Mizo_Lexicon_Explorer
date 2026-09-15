#!/usr/bin/env python3
"""
JASS Mizo Lexicon Explorer v2.0
--------------------------------
Clean rebuild for JASS_Mizo_Lexicon.db.

Expected main database schema:
  lexicon(
      id, word, normalized, frequency, source_count, sources,
      english_equivalents, sentiment_positive, sentiment_neutral,
      sentiment_negative, example_mizo, example_english
  )
  lexicon_fts FTS5(content='lexicon', content_rowid='id')
  lexicon_metadata(key, value)

Optional companion databases in the same folder:
  Mizo_English_Parallel_20K.db
  Mizo_Parallel_Corpus.db
  Mizo_YouTube_Sentiment.db

The explorer deliberately does NOT require pandas, numpy, torch, transformers,
or any other heavy package. It uses only Python + PySide6 + SQLite.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStatusBar, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QToolBar, QVBoxLayout, QWidget, QHeaderView
)

APP_NAME = "JASS Mizo Lexicon Explorer"
VERSION = "2.0"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "JASS_Mizo_Lexicon.db"

COMPANION_DBS = [
    BASE_DIR / "Mizo_English_Parallel_20K.db",
    BASE_DIR / "Mizo_Parallel_Corpus.db",
]

SOURCE_LABELS = {
    "JASS_Mizo_Corpus.db": "JASS Mizo Corpus",
    "Mizo_English_Parallel_20K.db": "Mizo-English Parallel 20K",
    "Mizo_Parallel_Corpus.db": "Mizo Parallel Corpus",
    "Mizo_YouTube_Sentiment.db": "Mizo YouTube Sentiment",
}

STYLE = """
QMainWindow, QWidget {
    background: #f6f7f9;
    color: #17202a;
    font-size: 10pt;
}
QLineEdit, QComboBox, QPushButton {
    min-height: 34px;
    border: 1px solid #c9ced6;
    border-radius: 7px;
    background: white;
    padding: 3px 10px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #2677d9;
}
QPushButton {
    padding-left: 14px;
    padding-right: 14px;
}
QPushButton:hover {
    background: #eef5ff;
}
QListWidget, QTableWidget, QTextBrowser {
    background: white;
    border: 1px solid #d5d9df;
    border-radius: 7px;
}
QListWidget::item {
    padding: 9px 8px;
    border-bottom: 1px solid #eef0f3;
}
QListWidget::item:selected {
    background: #dbeeff;
    color: #082d55;
    border-left: 3px solid #1976d2;
}
QGroupBox {
    background: white;
    border: 1px solid #cfd4dc;
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QTabWidget::pane {
    background: white;
    border: 1px solid #d5d9df;
    border-radius: 7px;
}
QTabBar::tab {
    padding: 8px 14px;
}
QTabBar::tab:selected {
    background: white;
    border-bottom: 2px solid #1976d2;
}
QToolBar {
    background: white;
    border-bottom: 1px solid #d9dde3;
    spacing: 5px;
    padding: 5px;
}
QStatusBar {
    background: white;
    border-top: 1px solid #d9dde3;
}
QHeaderView::section {
    background: #eef1f5;
    padding: 7px;
    border: none;
    font-weight: 600;
}
"""

def esc(s: object) -> str:
    return ("" if s is None else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def fmt_num(n: object) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "0"

def sentiment(v: object) -> str:
    try:
        return f"{float(v):.3f}"
    except Exception:
        return "—"

def split_sources(value: str) -> list[str]:
    if not value:
        return []
    try:
        obj = json.loads(value)
        if isinstance(obj, list):
            return [str(x) for x in obj if str(x).strip()]
    except Exception:
        pass
    return [x.strip() for x in re.split(r"[,;\n|]+", value) if x.strip()]

class LexiconDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._check_schema()

    def _check_schema(self):
        tables = {
            r["name"] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        missing = [x for x in ("lexicon", "lexicon_fts", "lexicon_metadata") if x not in tables]
        if missing:
            raise RuntimeError(
                "This is not a JASS Mizo Lexicon database.\n"
                f"Missing: {', '.join(missing)}"
            )

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def metadata(self) -> dict[str, str]:
        return dict(self.conn.execute(
            "SELECT key,value FROM lexicon_metadata ORDER BY key"
        ).fetchall())

    def counts(self) -> dict[str, int]:
        total = self.conn.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
        return {
            "words": total,
            "frequency": self.conn.execute(
                "SELECT COALESCE(SUM(frequency),0) FROM lexicon"
            ).fetchone()[0],
            "sources": self.conn.execute(
                "SELECT COUNT(DISTINCT source_count) FROM lexicon"
            ).fetchone()[0],
        }

    def search(self, query: str, mode: str, limit: int = 300) -> list[sqlite3.Row]:
        q = query.strip()
        if not q:
            return []

        if mode == "Exact":
            return self.conn.execute(
                """SELECT * FROM lexicon
                   WHERE word = ? OR normalized = ?
                   ORDER BY frequency DESC LIMIT ?""",
                (q, q.lower(), limit)
            ).fetchall()

        if mode == "Prefix":
            return self.conn.execute(
                """SELECT * FROM lexicon
                   WHERE normalized LIKE ? ESCAPE '\\'
                   ORDER BY frequency DESC LIMIT ?""",
                (q.lower().replace("\\", "\\\\") + "%", limit)
            ).fetchall()

        if mode == "Contains":
            needle = f"%{q}%"
            return self.conn.execute(
                """SELECT * FROM lexicon
                   WHERE word LIKE ? OR normalized LIKE ?
                      OR english_equivalents LIKE ?
                   ORDER BY frequency DESC LIMIT ?""",
                (needle, needle, needle, limit)
            ).fetchall()

        if mode == "English":
            needle = f"%{q}%"
            return self.conn.execute(
                """SELECT * FROM lexicon
                   WHERE english_equivalents LIKE ?
                      OR example_english LIKE ?
                   ORDER BY frequency DESC LIMIT ?""",
                (needle, needle, limit)
            ).fetchall()

        # FTS
        safe = re.sub(r'["*:^()]', " ", q).strip()
        if not safe:
            return []
        try:
            return self.conn.execute(
                """SELECT l.*
                   FROM lexicon_fts f
                   JOIN lexicon l ON l.id = f.rowid
                   WHERE lexicon_fts MATCH ?
                   ORDER BY l.frequency DESC LIMIT ?""",
                (f'"{safe}"', limit)
            ).fetchall()
        except sqlite3.Error:
            return self.search(q, "Contains", limit)

    def top_words(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM lexicon ORDER BY frequency DESC LIMIT ?", (limit,)
        ).fetchall()

    def get_word(self, word: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM lexicon WHERE word = ? LIMIT 1", (word,)
        ).fetchone()

class TranslationResolver:
    """Find a real English translation/example from the companion parallel DBs."""

    def __init__(self, paths: Iterable[Path]):
        self.connections: list[tuple[Path, sqlite3.Connection]] = []
        for p in paths:
            if not p.exists():
                continue
            try:
                c = sqlite3.connect(str(p))
                c.row_factory = sqlite3.Row
                tables = {
                    r["name"] for r in c.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "mizo_parallel" in tables:
                    cols = {
                        r["name"] for r in c.execute(
                            "PRAGMA table_info(mizo_parallel)"
                        )
                    }
                    if {"mizo", "english"} <= cols:
                        self.connections.append((p, c))
            except Exception:
                pass

    def close(self):
        for _, c in self.connections:
            try:
                c.close()
            except Exception:
                pass

    def lookup(self, word: str, example_mizo: str = "", limit: int = 20) -> list[dict]:
        results: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for path, conn in self.connections:
            queries = []
            if example_mizo:
                queries.append((
                    "SELECT mizo,english FROM mizo_parallel "
                    "WHERE mizo = ? LIMIT ?", (example_mizo, limit)
                ))
            queries.append((
                "SELECT mizo,english FROM mizo_parallel "
                "WHERE mizo LIKE ? LIMIT ?", (f"%{word}%", limit)
            ))

            for sql, args in queries:
                try:
                    rows = conn.execute(sql, args).fetchall()
                except sqlite3.Error:
                    continue
                for r in rows:
                    m = str(r["mizo"] or "").strip()
                    e = str(r["english"] or "").strip()
                    if not e:
                        continue
                    key = (m, e)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        "mizo": m,
                        "english": e,
                        "source": path.name,
                    })
                    if len(results) >= limit:
                        return results
        return results

class InfoDialog(QDialog):
    def __init__(self, db: LexiconDB, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JASS Mizo Lexicon — Database Information")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        meta = db.metadata()
        counts = db.counts()
        html = [
            f"<h2>{APP_NAME} {VERSION}</h2>",
            "<p><b>Database:</b> " + esc(db.path) + "</p>",
            f"<p><b>Unique words:</b> {fmt_num(counts['words'])}<br>"
            f"<b>Total token frequency:</b> {fmt_num(counts['frequency'])}</p>",
            "<h3>Metadata</h3><table width='100%' cellspacing='6'>"
        ]
        for k, v in meta.items():
            html.append(f"<tr><td><b>{esc(k)}</b></td><td>{esc(v)}</td></tr>")
        html.append("</table>")
        browser.setHtml("".join(html))
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

class MainWindow(QMainWindow):
    def __init__(self, db: LexiconDB):
        super().__init__()
        self.db = db
        self.translator = TranslationResolver(COMPANION_DBS)
        self.results: list[sqlite3.Row] = []
        self.current_row: sqlite3.Row | None = None

        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1500, 900)
        self.setMinimumSize(1100, 700)

        self._build_actions()
        self._build_ui()
        self._load_top_words()

        self.statusBar().showMessage("Ready")

    def closeEvent(self, event):
        self.translator.close()
        self.db.close()
        event.accept()

    def _build_actions(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        new_search = QAction("New Search", self)
        new_search.setShortcut("Ctrl+L")
        new_search.triggered.connect(lambda: (self.search_edit.setFocus(), self.search_edit.selectAll()))
        toolbar.addAction(new_search)

        toolbar.addSeparator()

        info = QAction("Database Info", self)
        info.triggered.connect(self.show_info)
        toolbar.addAction(info)

        export = QAction("Export Results", self)
        export.triggered.connect(self.export_results)
        toolbar.addAction(export)

        toolbar.addSeparator()

        quit_action = QAction("Exit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        toolbar.addAction(quit_action)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(8)

        title = QLabel(f"<b>{APP_NAME}</b>")
        title.setStyleSheet("font-size: 25px;")
        subtitle = QLabel(
            "Mizo dictionary • corpus lexicon • English equivalents • "
            "real usage examples • sentiment evidence"
        )
        subtitle.setStyleSheet("color:#64748b; font-size:11px;")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search a Mizo word, phrase, or English meaning…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.do_search)

        self.mode = QComboBox()
        self.mode.addItems(["FTS", "Exact", "Prefix", "Contains", "English"])
        self.mode.setToolTip("Choose how the search is performed.")

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.do_search)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_search)

        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.mode)
        search_row.addWidget(search_btn)
        search_row.addWidget(clear_btn)
        outer.addLayout(search_row)

        # Compact database statistics
        cards = QHBoxLayout()
        self.card_words = self._card("WORDS", "—")
        self.card_frequency = self._card("TOTAL FREQUENCY", "—")
        self.card_results = self._card("RESULTS", "—")
        cards.addWidget(self.card_words)
        cards.addWidget(self.card_frequency)
        cards.addWidget(self.card_results)
        cards.addStretch(1)
        outer.addLayout(cards)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 5, 0)

        left_header = QHBoxLayout()
        h = QLabel("Search Results")
        h.setStyleSheet("font-size:17px; font-weight:700;")
        self.result_count = QLabel("")
        self.result_count.setStyleSheet("color:#64748b;")
        left_header.addWidget(h)
        left_header.addStretch()
        left_header.addWidget(self.result_count)
        left_layout.addLayout(left_header)

        self.result_list = QListWidget()
        self.result_list.setUniformItemSizes(True)
        self.result_list.currentRowChanged.connect(self.on_result_selected)
        left_layout.addWidget(self.result_list, 1)

        self.quick_hint = QLabel("Tip: select a result to inspect its translation and evidence.")
        self.quick_hint.setStyleSheet("color:#64748b; padding:4px;")
        left_layout.addWidget(self.quick_hint)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(5, 0, 0, 0)

        self.profile = QGroupBox("Lexical Profile")
        profile_grid = QGridLayout(self.profile)
        profile_grid.setHorizontalSpacing(18)
        profile_grid.setVerticalSpacing(8)

        self.word_value = QLabel("—")
        self.freq_value = QLabel("—")
        self.source_count_value = QLabel("—")
        self.english_value = QLabel("—")
        self.sentiment_value = QLabel("—")
        self.sources_value = QLabel("—")

        self.english_value.setWordWrap(True)
        self.sources_value.setWordWrap(True)
        self.english_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sources_value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        labels = [
            ("Mizo word", self.word_value),
            ("Frequency", self.freq_value),
            ("Source count", self.source_count_value),
            ("English equivalents", self.english_value),
            ("Sentiment evidence", self.sentiment_value),
            ("Corpus sources", self.sources_value),
        ]
        for row, (label, widget) in enumerate(labels):
            profile_grid.addWidget(QLabel(f"<b>{label}</b>"), row, 0)
            profile_grid.addWidget(widget, row, 1)
        profile_grid.setColumnStretch(1, 1)
        right_layout.addWidget(self.profile)

        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs, 1)

        self.overview = QTextBrowser()
        self.overview.setOpenExternalLinks(False)
        self.tabs.addTab(self.overview, "Overview")

        self.examples = QTableWidget(0, 3)
        self.examples.setHorizontalHeaderLabels(["Mizo usage", "English translation", "Source"])
        self.examples.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.examples.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.examples.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.examples.setWordWrap(True)
        self.examples.setAlternatingRowColors(True)
        self.examples.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.examples, "Usage & Translation")

        self.sentiment_table = QTableWidget(0, 3)
        self.sentiment_table.setHorizontalHeaderLabels(["Sentiment", "Evidence score", "Meaning"])
        self.sentiment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.sentiment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sentiment_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sentiment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.sentiment_table, "Sentiment")

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([500, 950])
        outer.addWidget(splitter, 1)

    def _card(self, label: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background:white; border:1px solid #d5d9df; border-radius:8px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 8, 14, 8)
        a = QLabel(label)
        a.setStyleSheet("color:#64748b; font-size:9px; font-weight:700;")
        b = QLabel(value)
        b.setStyleSheet("font-size:17px; font-weight:700;")
        lay.addWidget(a)
        lay.addWidget(b)
        frame.value_label = b
        return frame

    def _load_top_words(self):
        c = self.db.counts()
        self.card_words.value_label.setText(fmt_num(c["words"]))
        self.card_frequency.value_label.setText(fmt_num(c["frequency"]))
        self.card_results.value_label.setText("0")
        self.result_list.clear()
        self.results = self.db.top_words(200)
        self._populate_results(self.results, "Top words")
        if self.results:
            self.result_list.setCurrentRow(0)

    def _populate_results(self, rows: list[sqlite3.Row], caption: str = "Results"):
        self.result_list.clear()
        for row in rows:
            word = str(row["word"])
            freq = fmt_num(row["frequency"])
            sc = fmt_num(row["source_count"])
            eq = str(row["english_equivalents"] or "").replace("\n", ", ")
            if len(eq) > 95:
                eq = eq[:92] + "…"
            text = f"{word}   •   {freq}   •   {sc} sources   —   {eq}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, row["id"])
            self.result_list.addItem(item)

        self.result_count.setText(f"{len(rows):,} shown")
        self.card_results.value_label.setText(fmt_num(len(rows)))
        self.quick_hint.setText(
            f"{caption}. Double-click a word to put it into the search box."
        )

    def do_search(self):
        q = self.search_edit.text().strip()
        if not q:
            self._load_top_words()
            return
        self.results = self.db.search(q, self.mode.currentText(), 300)
        self._populate_results(self.results, f"Search results for “{q}”")
        self.statusBar().showMessage(
            f"{len(self.results):,} result(s) for “{q}”"
        )
        if self.results:
            self.result_list.setCurrentRow(0)
        else:
            self.clear_details()

    def clear_search(self):
        self.search_edit.clear()
        self._load_top_words()
        self.statusBar().showMessage("Showing most frequent Mizo words")

    def on_result_selected(self, index: int):
        if index < 0 or index >= len(self.results):
            return
        row = self.results[index]
        self.current_row = row
        self.show_word(row)

    def show_word(self, row: sqlite3.Row):
        word = str(row["word"])
        self.word_value.setText(esc(word))
        self.freq_value.setText(fmt_num(row["frequency"]))
        self.source_count_value.setText(fmt_num(row["source_count"]))

        equivalents = str(row["english_equivalents"] or "").strip()
        self.english_value.setText(esc(equivalents) if equivalents else "No English equivalents recorded.")

        sp = sentiment(row["sentiment_positive"])
        sn = sentiment(row["sentiment_neutral"])
        sx = sentiment(row["sentiment_negative"])
        self.sentiment_value.setText(
            f"<b>Positive</b> {sp}   |   <b>Neutral</b> {sn}   |   <b>Negative</b> {sx}"
        )

        srcs = split_sources(str(row["sources"] or ""))
        self.sources_value.setText(
            "<br>".join(esc(SOURCE_LABELS.get(s, s)) for s in srcs)
            if srcs else "No source list recorded."
        )

        example_mizo = str(row["example_mizo"] or "").strip()
        example_english = str(row["example_english"] or "").strip()

        # Critical fix: never put a database filename into the English column.
        # If the lexicon has no translation, query the real parallel corpora.
        examples = []
        if example_mizo and example_english:
            examples.append({
                "mizo": example_mizo,
                "english": example_english,
                "source": "Lexicon",
            })

        for item in self.translator.lookup(word, example_mizo, 30):
            key = (item["mizo"], item["english"])
            if not any((x["mizo"], x["english"]) == key for x in examples):
                examples.append(item)

        self._fill_examples(examples)
        self._fill_sentiment(row)

        overview = [
            f"<h2>{esc(word)}</h2>",
            f"<p><b>Frequency:</b> {fmt_num(row['frequency'])}</p>",
            f"<p><b>English equivalents:</b> {esc(equivalents) if equivalents else 'Not available'}</p>",
            "<h3>How to read this entry</h3>",
            "<p>The frequency is the observed corpus frequency. "
            "English equivalents are corpus-derived associations, not necessarily "
            "a single dictionary definition.</p>",
        ]
        if examples:
            overview.append(
                f"<p><b>Translation evidence:</b> {len(examples)} bilingual usage example(s) "
                "were found. Open <b>Usage &amp; Translation</b> to inspect them.</p>"
            )
        else:
            overview.append(
                "<p><b>Translation evidence:</b> no bilingual example was found for this entry.</p>"
            )
        self.overview.setHtml("".join(overview))
        self.tabs.setCurrentIndex(0)

    def _fill_examples(self, examples: list[dict]):
        self.examples.setRowCount(0)
        for ex in examples[:100]:
            r = self.examples.rowCount()
            self.examples.insertRow(r)
            self.examples.setItem(r, 0, QTableWidgetItem(str(ex["mizo"])))
            self.examples.setItem(r, 1, QTableWidgetItem(str(ex["english"])))
            self.examples.setItem(
                r, 2, QTableWidgetItem(SOURCE_LABELS.get(ex["source"], ex["source"]))
            )
        self.examples.resizeRowsToContents()

    def _fill_sentiment(self, row: sqlite3.Row):
        data = [
            ("POSITIVE", row["sentiment_positive"], "Positive-context evidence"),
            ("NEUTRAL", row["sentiment_neutral"], "Neutral-context evidence"),
            ("NEGATIVE", row["sentiment_negative"], "Negative-context evidence"),
        ]
        self.sentiment_table.setRowCount(0)
        for name, value, desc in data:
            r = self.sentiment_table.rowCount()
            self.sentiment_table.insertRow(r)
            self.sentiment_table.setItem(r, 0, QTableWidgetItem(name))
            self.sentiment_table.setItem(r, 1, QTableWidgetItem(sentiment(value)))
            self.sentiment_table.setItem(r, 2, QTableWidgetItem(desc))

    def clear_details(self):
        self.current_row = None
        self.word_value.setText("—")
        self.freq_value.setText("—")
        self.source_count_value.setText("—")
        self.english_value.setText("—")
        self.sentiment_value.setText("—")
        self.sources_value.setText("—")
        self.overview.clear()
        self.examples.setRowCount(0)
        self.sentiment_table.setRowCount(0)

    def show_info(self):
        InfoDialog(self.db, self).exec()

    def export_results(self):
        if not self.results:
            QMessageBox.information(self, "Export", "There are no results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Lexicon Results", "mizo_lexicon_results.tsv",
            "TSV files (*.tsv);;CSV files (*.csv);;Text files (*.txt)"
        )
        if not path:
            return
        try:
            import csv
            delim = "\t" if path.lower().endswith(".tsv") else ","
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=delim)
                w.writerow([
                    "word", "frequency", "source_count",
                    "english_equivalents", "sentiment_positive",
                    "sentiment_neutral", "sentiment_negative"
                ])
                for r in self.results:
                    w.writerow([
                        r["word"], r["frequency"], r["source_count"],
                        r["english_equivalents"], r["sentiment_positive"],
                        r["sentiment_neutral"], r["sentiment_negative"]
                    ])
            self.statusBar().showMessage(f"Exported {len(self.results):,} rows")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

def choose_database() -> Path | None:
    if DEFAULT_DB.exists():
        return DEFAULT_DB
    path, _ = QFileDialog.getOpenFileName(
        None, "Open JASS Mizo Lexicon Database",
        str(BASE_DIR), "SQLite databases (*.db *.sqlite *.sqlite3)"
    )
    return Path(path) if path else None

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setStyleSheet(STYLE)

    # Make the UI behave well on high-DPI Windows displays.
    font = QFont()
    font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
    app.setFont(font)

    db_path = choose_database()
    if not db_path:
        return 0

    try:
        db = LexiconDB(db_path)
    except Exception as e:
        QMessageBox.critical(None, "Database Error", str(e))
        return 1

    win = MainWindow(db)
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
