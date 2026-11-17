#!/usr/bin/env python3
"""Static, read-only snapshot of a MediaWiki (stdlib only; runs on the old server).

  python3 crawl_mediawiki.py http://192.168.56.5 /root/wiki-static "Osolia Wiki" "wiki.osolia.xyz"

Saves rendered pages to /wiki/<Title>.html (GitHub Pages serves /wiki/<Title> from that),
namespaced pages to /wiki/<Ns>/<Title>.html, and only the CSS/images the pages reference.
"""
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE, OUT, SITENAME, DOMAIN = sys.argv[1].rstrip("/"), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
NAMESPACES = [0, 2, 4, 6, 12, 14]          # main, User, Project, File, Help, Category
BAD = re.compile(r'[<>:"|?*\\]')            # not allowed in Windows filenames
OUT.mkdir(parents=True, exist_ok=True)
assets = {}                                 # original url-path -> local path
failed = []


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "archive-crawler"}), timeout=60) as r:
        return r.read(), r.headers.get("Content-Type", "")


def api(**params):
    params.update(format="json", formatversion="2")
    return json.loads(get(BASE + "/api.php?" + urllib.parse.urlencode(params))[0])


siteinfo = api(action="query", meta="siteinfo", siprop="namespaces|general")["query"]
ns_names = {int(k): v["name"] for k, v in siteinfo["namespaces"].items()}
ns_by_name = {v.lower(): k for k, v in ns_names.items() if v}
for alias in ("Image",):
    ns_by_name.setdefault(alias.lower(), 6)


def local_page_path(title):
    """'Category:Foo bar' -> 'wiki/Category/Foo_bar.html'"""
    title = title.replace(" ", "_")
    ns, _, rest = title.partition(":")
    if rest and ns.replace("_", " ").lower() in ns_by_name and ns_by_name[ns.replace("_", " ").lower()] != 0:
        rel = f"{ns}/{rest}"
    else:
        rel = title
    rel = "/".join(BAD.sub("_", part) for part in rel.split("/"))
    return f"wiki/{rel}.html"


def page_url(local):  # wiki/Category/Foo.html -> /wiki/Category/Foo
    return "/" + urllib.parse.quote(local[:-5])


titles = []
for ns in NAMESPACES:
    cont = {}
    while True:
        r = api(action="query", list="allpages", apnamespace=ns, aplimit="max", **cont)
        titles += [p["title"] for p in r["query"]["allpages"]]
        if "continue" not in r:
            break
        cont = {"apcontinue": r["continue"]["apcontinue"]}
print(f"{len(titles)} pages to fetch")

title_map = {t.replace(" ", "_"): local_page_path(t) for t in titles}


def fetch_asset(path):
    """path like /images/a/ab/X.png or /load.php?... ; returns local URL"""
    if path in assets:
        return assets[path]
    p = urllib.parse.urlsplit(path)
    if p.path.endswith("load.php"):
        name = "_static/load-" + hashlib.sha1(path.encode()).hexdigest()[:12] + ".css"
    else:
        name = urllib.parse.unquote(p.path).lstrip("/")
        if p.query:
            name += "-" + hashlib.sha1(p.query.encode()).hexdigest()[:8]
        name = "/".join(BAD.sub("_", part) for part in name.split("/"))
    assets[path] = "/" + urllib.parse.quote(name)
    try:
        body, ctype = get(BASE + path)
    except Exception as e:
        failed.append(f"{path}: {e}")
        return assets[path]
    if name.endswith(".css") or "text/css" in ctype:
        css = body.decode("utf-8", "replace")
        base_dir = p.path.rsplit("/", 1)[0] + "/"
        def css_url(m):
            u = m.group(2).strip()
            if u.startswith(("data:", "http:", "https:", "#")):
                return m.group(0)
            absu = urllib.parse.urljoin(base_dir, u)
            return f"url({m.group(1)}{fetch_asset(absu)}{m.group(1)})"
        css = re.sub(r"url\((['\"]?)([^'\")]+)\1\)", css_url, css)
        body = css.encode()
    dst = OUT / urllib.parse.unquote(assets[path].lstrip("/"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    return assets[path]


HIDE = """<style id="archive-overrides">
#p-cactions,#p-personal,#p-search,#p-tb,#ca-edit,#ca-viewsource,#ca-history,#ca-talk,#ca-watch,#ca-unwatch,
#ca-ve-edit,#ca-addsection,#p-views,.vector-user-links,.vector-page-tools,.vector-page-tools-landmark,
.vector-search-box,#p-associated-pages,.mw-editsection,#footer-places,.mw-portlet-coll-print_export,
#n-recentchanges,#n-randompage,#n-help-mediawiki,#t-specialpages,.printfooter,#ca-nstab-talk,.catlinks .mw-hidden-catlinks{display:none!important}
.archive-banner{background:#fff6dc;color:#5a4300;border:1px solid #f0d98a;padding:8px 12px;margin:0 0 12px;font-size:14px;border-radius:4px}
</style>"""
BANNER = (f'<div class="archive-banner"><strong>Read-only archive.</strong> This is a static copy of '
          f'{SITENAME} ({DOMAIN}). Editing, search and page history are not available.</div>')

ATTR = re.compile(r'(\s(?:href|src))="([^"]*)"')
SRCSET = re.compile(r'\ssrcset="([^"]*)"')
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)


def rewrite(html):
    html = SCRIPT.sub("", html)

    def fix(url):
        url = url.replace("&amp;", "&")
        if url.startswith(("http://", "https://", "//")):
            sp = urllib.parse.urlsplit(url if not url.startswith("//") else "https:" + url)
            if sp.netloc not in (DOMAIN, urllib.parse.urlsplit(BASE).netloc):
                return url.replace("&", "&amp;")
            url = sp.path + ("?" + sp.query if sp.query else "")
        if url.startswith("/wiki/"):
            path, _, frag = url.partition("#")
            t = urllib.parse.unquote(path[len("/wiki/"):])
            if t in title_map:
                return page_url(title_map[t]) + ("#" + frag if frag else "")
            return url.replace("&", "&amp;")
        if url.startswith(("/images/", "/resources/", "/load.php", "/extensions/", "/skins/")) and "only=scripts" not in url:
            return fetch_asset(url)
        return url.replace("&", "&amp;")

    html = ATTR.sub(lambda m: f'{m.group(1)}="{fix(m.group(2))}"', html)
    html = SRCSET.sub(lambda m: ' srcset="' + ", ".join(
        " ".join([fix(part.split()[0])] + part.split()[1:]) for part in m.group(1).split(",") if part.strip()) + '"', html)
    html = html.replace("</head>", HIDE + "\n</head>", 1)
    html = re.sub(r'(<div id="contentSub"|<div id="siteSub")', BANNER + r"\1", html, count=1)
    if BANNER not in html:
        html = re.sub(r'(<main\b[^>]*>|<div id="content"[^>]*>)', r"\1" + BANNER, html, count=1)
    return html


for i, t in enumerate(titles, 1):
    local = title_map[t.replace(" ", "_")]
    try:
        body, _ = get(BASE + "/wiki/" + urllib.parse.quote(t.replace(" ", "_")))
    except Exception as e:
        failed.append(f"{t}: {e}")
        continue
    dst = OUT / local
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(rewrite(body.decode("utf-8", "replace")), encoding="utf-8")
    if i % 50 == 0:
        print(f"  {i}/{len(titles)}")

main = siteinfo["general"].get("mainpage", "Main Page").replace(" ", "_")
(OUT / "index.html").write_text(
    f'<!doctype html><meta charset="utf-8"><title>{SITENAME}</title>'
    f'<meta http-equiv="refresh" content="0; url={page_url(title_map.get(main, "wiki/Main_Page.html"))}">', encoding="utf-8")

# old-URL shapes -> archive paths
mapping = {t: page_url(p) for t, p in title_map.items()}
(OUT / "404.html").write_text("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Not in the archive</title><script>
var M=""" + json.dumps(mapping, ensure_ascii=False) + """;
(function(){var t=null,p=decodeURIComponent(location.pathname),q=new URLSearchParams(location.search);
if(p.indexOf('/wiki/')===0)t=p.slice(6);else if(q.get('title'))t=q.get('title');
if(t){t=t.replace(/ /g,'_');if(M[t]){location.replace(M[t]+location.hash);return;}
var k=Object.keys(M).find(function(x){return x.toLowerCase()===t.toLowerCase();});if(k)location.replace(M[k]);}})();
</script><style>body{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px}</style></head>
<body><h1>Not in the archive</h1><p>This page of """ + SITENAME + """ wasn't kept. Talk pages, page history,
special pages and editing were not archived.</p><p><a href="/">Go to the main page</a></p></body></html>""", encoding="utf-8")
(OUT / "CNAME").write_text(DOMAIN + "\n")
(OUT / ".nojekyll").write_text("")

print(f"pages: {len(titles)}  assets: {len(assets)}  failed: {len(failed)}")
for f in failed[:30]:
    print("  FAIL", f)
