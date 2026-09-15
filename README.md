<img width="1910" height="986" alt="image" src="https://github.com/user-attachments/assets/81a1068b-6a04-45a0-87d0-75c02147820a" />

# JASS Mizo Lexicon Explorer v2.0

A lightweight desktop application for exploring a large Mizo lexical database built from Mizo-English parallel corpora, Mizo YouTube sentiment data, and a large Mizo text corpus.

JASS Mizo Lexicon Explorer combines:

- Mizo word lookup
- Corpus frequency
- English equivalents
- Corpus source information
- Real bilingual usage examples
- English translations
- Sentiment evidence
- Full-text search
- Prefix and substring search
- Search-result export
- SQLite/FTS5 database exploration

The application is designed to work offline and does **not** require heavy AI/ML frameworks.

---

## Features

### 🔎 Multiple Search Modes

The explorer supports five search modes:

| Mode | Description |
|---|---|
| **FTS** | SQLite FTS5 full-text search |
| **Exact** | Exact Mizo word lookup |
| **Prefix** | Find words beginning with the search term |
| **Contains** | Search inside Mizo words and English equivalents |
| **English** | Search English equivalents and English usage examples |

Press **Enter** to search.

---

## 📖 Lexical Profile

Selecting a result displays a detailed lexical profile containing:

- Mizo word
- Corpus frequency
- Number of contributing sources
- English equivalents
- Sentiment evidence
- Corpus sources

Example:

```text
Mizo word:       hmangaihna
Frequency:       17,508
Source count:    4

English equivalents:
love, us, god, jehovah, loving, jesus, all, john
