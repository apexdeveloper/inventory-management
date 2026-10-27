#!/usr/bin/env python3
"""Structural inventory of Vue single-file components.

Collects mechanical facts (sizes, script style, v-for keys, duplicated helpers,
duplicated CSS, repeated modal markup, eager routes) so the analysis can focus
on judgment. Regex-based: every finding is a lead to confirm by reading the code.

Usage: python3 -I analyze_vue.py [SRC_DIR] [--json]
SRC_DIR defaults to client/src. Standard library only.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LARGE_FILE_LINES = 500
LARGE_SCRIPT_LINES = 300
MIN_DUPLICATE_CSS_DECLS = 3

BLOCK_RE = {
    "script": re.compile(r"<script\b[^>]*>(.*?)</script>", re.S),
    "style": re.compile(r"<style\b[^>]*>(.*?)</style>", re.S),
}
# Opening tags that carry a v-for; [^>] stops at the first '>', which is good enough
# for this codebase's templates (comparisons inside attributes are rare)
VFOR_TAG_RE = re.compile(r"<([a-zA-Z][\w-]*)\b[^>]*\bv-for=\"([^\"]*)\"[^>]*>", re.S)
FUNC_DEF_RES = [
    re.compile(r"\b(?:const|let)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>"),
    re.compile(r"\bfunction\s+([a-zA-Z_]\w*)\s*\("),
]
INTERPOLATION_CALL_RE = re.compile(r"\{\{[^}]*?\b([a-zA-Z_][\w.]*)\(")
EXPORT_RE = re.compile(r"export\s+(?:async\s+)?(?:function|const|let)\s+([a-zA-Z_]\w*)")
MODAL_SHELL_RE = re.compile(r"class=\"[^\"]*\bmodal-(?:overlay|backdrop)\b")
BUILTIN_COMPONENTS = {"RouterView", "RouterLink", "Transition", "TransitionGroup", "Teleport", "KeepAlive", "Suspense", "Component"}
# Names too generic to count as duplication (lifecycle wrappers, event handlers)
GENERIC_NAMES = {"close", "handleClose", "load", "loadData", "fetchData", "init", "toggle", "t"}


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def template_span(text):
    """Outer <template> block; nested <template> tags make a non-greedy match wrong."""
    start = text.find("<template")
    end = text.rfind("</template>")
    if start == -1 or end == -1:
        return 0, ""
    return start, text[start:end]


def script_style(script):
    if re.search(r"<script\b[^>]*\bsetup\b", script["raw_tag"]):
        return "script-setup"
    if re.search(r"\bsetup\s*\(", script["body"]):
        return "options+setup()"
    return "options-api"


def parse_css_rules(css):
    """Yield (selector, normalized declarations) for flat rules; @media bodies are skipped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        decls = sorted(d.strip() for d in match.group(2).split(";") if d.strip())
        if decls:
            yield match.group(1).strip(), tuple(decls)


def analyze_file(path, root):
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(root))
    t_start, template = template_span(text)
    script_match = re.search(r"(<script\b[^>]*>)(.*?)</script>", text, re.S)
    script = {"raw_tag": script_match.group(1), "body": script_match.group(2)} if script_match else {"raw_tag": "", "body": ""}
    script_offset = script_match.start(2) if script_match else 0
    styles = BLOCK_RE["style"].findall(text)

    info = {
        "file": rel,
        "lines": text.count("\n") + 1,
        "template_lines": template.count("\n"),
        "script_lines": script["body"].count("\n"),
        "style_lines": sum(s.count("\n") for s in styles),
        "script_style": script_style(script) if script_match else "none",
        "counts": {
            name: len(re.findall(rf"\b{name}\s*\(", script["body"]))
            for name in ("ref", "reactive", "computed", "watch", "watchEffect", "shallowRef")
        },
        "deep_watchers": [line_of(text, script_offset + m.start()) for m in re.finditer(r"deep\s*:\s*true", script["body"])],
        "api_calls": sorted(set(re.findall(r"\bapi\.(\w+)\(", script["body"]))),
        "interpolation_calls": len(INTERPOLATION_CALL_RE.findall(template)),
        "vfor": [],
        "functions": {},
        "modal_shell": bool(MODAL_SHELL_RE.search(template)),
        "unresolved_components": [],
        "css_rules": [],
    }

    # PascalCase tags with no matching import render as unknown elements, and Vue only warns at runtime
    imported = set(re.findall(r"import\s+(\w+)\s+from", script["body"]))
    for m in re.finditer(r"<([A-Z][A-Za-z0-9]+)\b", template):
        name = m.group(1)
        if name not in imported and name not in BUILTIN_COMPONENTS and name not in info["unresolved_components"]:
            info["unresolved_components"].append(name)

    for m in VFOR_TAG_RE.finditer(template):
        tag, expr = m.group(1), m.group(2)
        tag_text = m.group(0)
        key = re.search(r":key=\"([^\"]*)\"", tag_text)
        index_var = re.match(r"\s*\(\s*[^,]+,\s*(\w+)", expr)
        info["vfor"].append({
            "line": line_of(text, t_start + m.start()),
            "tag": tag,
            "expr": expr.strip(),
            "key": key.group(1) if key else None,
            # Index keys break element reuse when the list is filtered or sorted
            "index_key": bool(key and index_var and key.group(1).strip() == index_var.group(1)),
            "with_v_if": "v-if=" in tag_text,
            # A method call in the v-for source re-runs on every render
            "call_in_source": bool(re.search(r"\bin\s+[\w.]+\(", expr)),
        })

    for regex in FUNC_DEF_RES:
        for m in regex.finditer(script["body"]):
            info["functions"].setdefault(m.group(1), line_of(text, script_offset + m.start()))

    for style in styles:
        info["css_rules"].extend(parse_css_rules(style))
    return info


def collect_exports(src):
    """Names exported from utils/ and composables/, to spot local re-implementations."""
    exports = {}
    for folder in ("utils", "composables"):
        for path in sorted((src / folder).glob("*.js")) if (src / folder).is_dir() else []:
            for name in EXPORT_RE.findall(path.read_text(encoding="utf-8")):
                exports[name] = str(path.relative_to(src))
    return exports


def route_imports(src):
    main = src / "main.js"
    if not main.exists():
        return None
    text = main.read_text(encoding="utf-8")
    return {
        "eager_view_imports": re.findall(r"import\s+(\w+)\s+from\s+['\"][./]*views/", text),
        "lazy_view_imports": len(re.findall(r"import\(\s*['\"][./]*views/", text)),
    }


def unreferenced_components(src, vue_paths):
    """Components no other file imports; App.vue is the root, so it is never imported."""
    sources = {p: p.read_text(encoding="utf-8") for p in src.rglob("*") if p.suffix in (".vue", ".js") and "node_modules" not in p.parts}
    unused = []
    for path in vue_paths:
        if path.name == "App.vue":
            continue
        pattern = re.compile(rf"['\"][^'\"]*/{re.escape(path.stem)}(?:\.vue)?['\"]")
        if not any(pattern.search(text) for other, text in sources.items() if other != path):
            unused.append(str(path.relative_to(src)))
    return unused


def analyze(src):
    root = src
    vue_paths = [p for p in sorted(src.rglob("*.vue")) if "node_modules" not in p.parts]
    files = [analyze_file(p, root) for p in vue_paths]
    exports = collect_exports(src)

    func_sites = defaultdict(list)
    for f in files:
        for name, line in f["functions"].items():
            if name not in GENERIC_NAMES:
                func_sites[name].append(f"{f['file']}:{line}")

    css_sites = defaultdict(list)
    for f in files:
        for selector, decls in f["css_rules"]:
            if len(decls) >= MIN_DUPLICATE_CSS_DECLS:
                css_sites[decls].append(f"{f['file']} {selector}")

    return {
        "src": str(src),
        "files": [{k: v for k, v in f.items() if k not in ("functions", "css_rules")} for f in files],
        "large_files": [f["file"] for f in files if f["lines"] > LARGE_FILE_LINES or f["script_lines"] > LARGE_SCRIPT_LINES],
        "script_styles": {s: [f["file"] for f in files if f["script_style"] == s] for s in sorted({f["script_style"] for f in files})},
        "duplicate_functions": {n: s for n, s in sorted(func_sites.items()) if len({x.split(':')[0] for x in s}) > 1},
        "local_reimplementations": {
            n: {"shared": exports[n], "local": s} for n, s in sorted(func_sites.items()) if n in exports
        },
        # Only rules repeated across different files count; same-file repeats are usually intentional
        "duplicate_css": [s for s in css_sites.values() if len({x.split(' ')[0] for x in s}) > 1],
        "modal_shells": [f["file"] for f in files if f["modal_shell"]],
        "unreferenced": unreferenced_components(src, vue_paths),
        "routes": route_imports(src),
    }


def to_markdown(r):
    out = [f"# Vue structure inventory: `{r['src']}`", "", "Regex-based leads. Confirm each by reading the code before reporting it.", ""]
    out += ["## Components", "", "| File | Lines | Template | Script | Style | API | ref/computed/watch | v-for | Calls in {{ }} |", "|---|---|---|---|---|---|---|---|---|"]
    for f in sorted(r["files"], key=lambda f: -f["lines"]):
        c = f["counts"]
        out.append(f"| {f['file']} | {f['lines']} | {f['template_lines']} | {f['script_lines']} | {f['style_lines']} | {f['script_style']} | {c['ref'] + c['reactive']}/{c['computed']}/{c['watch'] + c['watchEffect']} | {len(f['vfor'])} | {f['interpolation_calls']} |")

    out += ["", "## Leads", ""]
    unresolved = [f"`{n}` in {f['file']}" for f in r["files"] for n in f["unresolved_components"]]
    if unresolved:
        out.append(f"- **Components used but not imported** (broken unless registered globally in main.js): {', '.join(unresolved)}")
    out.append(f"- **Large components** (> {LARGE_FILE_LINES} lines or script > {LARGE_SCRIPT_LINES}): {', '.join(r['large_files']) or 'none'}")
    if len(r["script_styles"]) > 1:
        out.append("- **Mixed script styles**: " + "; ".join(f"{s}: {len(v)}" for s, v in r["script_styles"].items()))

    vfor_issues = []
    for f in r["files"]:
        for v in f["vfor"]:
            problems = [p for p, hit in (("no :key", v["key"] is None), ("index as key", v["index_key"]),
                                         ("v-if on same tag", v["with_v_if"]), ("call in v-for source", v["call_in_source"])) if hit]
            if problems:
                vfor_issues.append(f"  - `{f['file']}:{v['line']}` `v-for=\"{v['expr']}\"`: {', '.join(problems)}")
    out.append(f"- **v-for problems**: {len(vfor_issues) or 'none'}")
    out += vfor_issues

    deep = [f"`{f['file']}:{l}`" for f in r["files"] for l in f["deep_watchers"]]
    if deep:
        out.append(f"- **Deep watchers**: {', '.join(deep)}")

    if r["local_reimplementations"]:
        out.append("- **Local copies of shared helpers**:")
        out += [f"  - `{n}` exported from `{v['shared']}`, redefined at {', '.join(v['local'])}" for n, v in r["local_reimplementations"].items()]
    if r["duplicate_functions"]:
        out.append("- **Same helper defined in several files** (compare bodies before suggesting a merge):")
        out += [f"  - `{n}`: {', '.join(s)}" for n, s in r["duplicate_functions"].items()]
    if len(r["modal_shells"]) > 1:
        out.append(f"- **Repeated modal shell markup** ({len(r['modal_shells'])} files): {', '.join(r['modal_shells'])}")
    if r["duplicate_css"]:
        out.append(f"- **CSS rules duplicated across files**: {len(r['duplicate_css'])} groups")
        out += [f"  - {', '.join(s[:4])}{' …' if len(s) > 4 else ''}" for s in sorted(r["duplicate_css"], key=len, reverse=True)[:10]]
    if r["unreferenced"]:
        out.append(f"- **Components nothing imports** (check for dynamic use before calling them dead): {', '.join(r['unreferenced'])}")
    routes = r["routes"]
    if routes and routes["eager_view_imports"] and not routes["lazy_view_imports"]:
        out.append(f"- **All {len(routes['eager_view_imports'])} routes imported eagerly** in main.js (no lazy-loaded views)")
    return "\n".join(out)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    src = Path(args[0] if args else "client/src").resolve()
    if not src.is_dir():
        sys.exit(f"Not a directory: {src}")
    report = analyze(src)
    print(json.dumps(report, indent=2) if "--json" in argv else to_markdown(report))


if __name__ == "__main__":
    main(sys.argv[1:])
