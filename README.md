# Osolia Wiki archive

Static, read-only snapshot of the MediaWiki at **wiki.osolia.xyz** (last edit Sep 1, 2025),
served by GitHub Pages from `docs/` at https://wiki.osolia.xyz.

Includes every article, category, file, user, help and project page as MediaWiki rendered it,
plus the images and styles those pages use. Page history, talk pages, special pages and
editing are not included. The full database dump and image folder are kept privately.

`tools/crawl_mediawiki.py` made the snapshot (stdlib Python, run against the live wiki):

```
python3 crawl_mediawiki.py http://<wiki-host> ./docs "Osolia Wiki" wiki.osolia.xyz
```
