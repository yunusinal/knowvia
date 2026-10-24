"""README mimari diyagramı: docs/assets/architecture-{dark,light}.svg dosyalarını üretir.

Diyagram elle yazılmış SVG'dir; GitHub onu resim olarak gösterir ve README `<picture>` ile temaya göre
koyu ya da açık sürümü seçer. Çalıştırma: uv run python -m scripts.draw_architecture
"""

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
WIDTH, HEIGHT = 1200, 800
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0B1220", "card": "#162033", "card2": "#0F172A", "line": "#2A3650", "text": "#E2E8F0",
        "strong": "#F8FAFC", "muted": "#94A3B8", "green": "#10B981", "yellow": "#FACC15", "ink": "#04130D",
    },
    "light": {
        "bg": "#FFFFFF", "card": "#F4F6FA", "card2": "#EAEEF4", "line": "#C9D2DE", "text": "#1E293B",
        "strong": "#0B1220", "muted": "#5B6878", "green": "#059669", "yellow": "#B45309", "ink": "#FFFFFF",
    },
}

STEP_W, STEP_GAP, LEFT = 170, 24, 30


def step_x(index: int) -> int:
    return LEFT + index * (STEP_W + STEP_GAP)


class Svg:
    def __init__(self, theme: dict[str, str]) -> None:
        self.t = theme
        self.parts: list[str] = []

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def text(self, x: float, y: float, value: str, size: float = 12, color: str = "text", weight: int = 400,
             anchor: str = "start") -> None:
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{self.t[color]}" '
                 f'text-anchor="{anchor}">{escape(value)}</text>')

    def box(self, x: float, y: float, w: float, h: float, fill: str = "card", stroke: str = "line",
            dashed: bool = False, radius: int = 10, width: float = 1.2) -> None:
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{self.t[fill]}" '
                 f'stroke="{self.t[stroke]}" stroke-width="{width}"{dash}/>')

    def card(self, x: float, y: float, w: float, h: float, title: str, lines: list[str],
             note: str = "", accent: str = "line", dashed: bool = False) -> None:
        self.box(x, y, w, h, stroke=accent, dashed=dashed)
        self.text(x + 14, y + 24, title, size=13, color="strong", weight=700)
        for i, line in enumerate(lines):
            self.text(x + 14, y + 44 + i * 17, line, size=12, color="muted")
        if note:
            self.text(x + 14, y + h - 14, note, size=11.5, color="yellow", weight=600)

    def arrow(self, x1: float, y1: float, x2: float, y2: float, color: str = "muted", dashed: bool = False,
              label: str = "") -> None:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        marker = "url(#arrow-green)" if color == "green" else "url(#arrow)"
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{self.t[color]}" stroke-width="1.6"'
                 f'{dash} marker-end="{marker}"/>')
        if label:
            self.text((x1 + x2) / 2 + 8, (y1 + y2) / 2 + 4, label, size=11, color="muted")

    def render(self) -> str:
        t = self.t
        defs = (
            "<defs>"
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{t["muted"]}"/></marker>'
            f'<marker id="arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{t["green"]}"/></marker>'
            "</defs>"
        )
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
            f'font-family="{FONT}" role="img" aria-labelledby="title desc">\n'
            '<title id="title">Knowvia architecture</title>\n'
            '<desc id="desc">A question passes Caddy, Streamlit and FastAPI, then six access-checked steps: identify the '
            "user, list permitted documents, hybrid search in Qdrant, re-check in SQLite with a similarity threshold, "
            "a grounded LLM call with authorized chunks only, and citation checks. Admin uploads are extracted, "
            "chunked, embedded and stored in Qdrant and SQLite.</desc>\n"
            f'{defs}\n<rect width="{WIDTH}" height="{HEIGHT}" fill="{t["bg"]}"/>\n{body}\n</svg>\n'
        )


def draw(theme: dict[str, str]) -> str:
    s = Svg(theme)

    # 1) Giriş katmanı: tarayıcı → Caddy → sayfa ve uygulama.
    s.text(LEFT, 28, "Edge", size=12, color="muted", weight=700)
    s.card(LEFT, 40, 170, 64, "Browser", ["visitor or team member"])
    s.card(step_x(1), 40, 170, 64, "Caddy", ["HTTPS, ports 80/443 only"], accent="green")
    s.card(step_x(2), 40, 170, 64, "Project page  /", ["static HTML, TR / EN"])
    s.card(step_x(3), 40, 364, 64, "Streamlit  /app/", ["chat, documents, tickets; holds only the JWT"])
    s.card(step_x(5), 40, 170, 64, "Rate limits", ["chat, login per minute"], dashed=True)
    s.arrow(LEFT + 170, 72, step_x(1) - 4, 72)
    s.arrow(step_x(1) + 170, 64, step_x(2) - 4, 64)
    s.add(f'<path d="M{step_x(1) + 170} 82 H{step_x(2) - 12} Q{step_x(2) - 6} 82 {step_x(2) - 6} 92 V118 '
          f'H{step_x(3) + 60} V108" fill="none" stroke="{theme["muted"]}" stroke-width="1.6" marker-end="url(#arrow)"/>')
    s.arrow(step_x(3) + 182, 104, step_x(3) + 182, 166, label="REST + JWT")

    # 2) Soru yolu: FastAPI içindeki altı adım.
    s.box(LEFT - 12, 150, WIDTH - 2 * (LEFT - 12), 214, fill="card2", stroke="line", radius=14)
    s.text(LEFT, 176, "FastAPI  ·  question path (every step fails closed)", size=13, color="strong", weight=700)
    steps = [
        ("1  Identify", ["JWT checked; role and", "department read from", "SQLite on every request"],
         "client claims ignored"),
        ("2  Allowlist", ["permitted document IDs", "for this user", "(company or department)"],
         "empty → no search"),
        ("3  Hybrid search", ["Qdrant: e5-large dense", "+ BM25 (Turkish stem),", "RRF; ACL filter on both"],
         ""),
        ("4  Re-check", ["every chunk checked", "again in SQLite;", "cosine ≥ threshold"],
         "nothing left → refusal"),
        ("5  Grounded LLM", ["only authorized chunks,", "sources as [S1]…[S5],", "documents are data"],
         ""),
        ("6  Verify citations", ["unknown [S#] removed;", "answer + source cards,", "or the same refusal"],
         "one refusal for both cases"),
    ]
    for i, (title, lines, note) in enumerate(steps):
        x = step_x(i)
        s.card(x, 196, STEP_W, 150, title, lines, note=note, accent="green" if i in (1, 3, 5) else "line")
        if i < len(steps) - 1:
            s.arrow(x + STEP_W + 2, 271, step_x(i + 1) - 4, 271, color="green")

    # 3) Veri katmanı.
    s.card(LEFT, 468, 364, 92, "SQLite  (SQLAlchemy)", ["users (Argon2 hashes), documents and visibility,",
                                                        "conversations, support tickets",
                                                        "the only source of permissions"], accent="green")
    s.card(step_x(2), 468, 170, 92, "Qdrant local", ["named vectors:", "dense 1024-d + bm25", "no permissions stored"])
    s.card(step_x(3), 468, 170, 92, "Re-ranker (GPU)", ["bge-reranker-v2-m3", "ONNX CUDA, 20 → 5", "GPU_ENABLED only"],
           dashed=True)
    s.card(step_x(4), 468, 364, 92, "LLM provider  (external)", ["OpenAI-compatible API, e.g. Groq gpt-oss-120b",
                                                                 "receives only the chunks this user may see",
                                                                 "missing key → 503 with setup help"], accent="yellow")
    s.arrow(step_x(0) + 85, 346, step_x(0) + 85, 464, dashed=True)
    s.arrow(step_x(1) + 85, 346, step_x(1) + 85, 464, dashed=True)
    s.arrow(step_x(2) + 85, 346, step_x(2) + 85, 464, dashed=True)
    s.arrow(step_x(3) + 85, 346, step_x(3) + 85, 464, dashed=True, label="optional")
    s.arrow(step_x(4) + 85, 346, step_x(4) + 85, 464, dashed=True)

    # 4) Belge yükleme yolu (admin).
    s.text(LEFT, 610, "Ingest  (admin only)", size=12, color="muted", weight=700)
    ingest = [
        ("Upload", ["PDF, TXT, Markdown", "up to 10 MB"]),
        ("Extract", ["text with page numbers", "duplicates by checksum"]),
        ("Chunk", ["one paragraph per chunk", "≤ 350 tokens, overlap"]),
        ("Embed", ["e5-large dense vectors", "+ BM25 sparse vectors"]),
        ("Store", ["vectors → Qdrant", "metadata, ACL → SQLite"]),
        ("Delete", ["access revoked first,", "vectors cleaned after"]),
    ]
    for i, (title, lines) in enumerate(ingest):
        x = step_x(i)
        s.card(x, 622, STEP_W, 78, title, lines, accent="green" if i == 5 else "line")
        if i < 4:
            s.arrow(x + STEP_W + 2, 661, step_x(i + 1) - 4, 661)

    # Alt bilgi.
    s.text(LEFT, 742, "Deployed as one container (API on 127.0.0.1 + Streamlit) behind Caddy with a persistent volume; "
           "demo data is synthetic and reset nightly.", size=12, color="muted")
    s.add(f'<rect x="{LEFT}" y="760" width="22" height="12" rx="3" fill="none" stroke="{theme["green"]}" stroke-width="1.6"/>')
    s.text(LEFT + 30, 770, "access-control gate", size=11.5, color="muted")
    s.add(f'<rect x="{LEFT + 170}" y="760" width="22" height="12" rx="3" fill="none" stroke="{theme["line"]}" '
          'stroke-width="1.6" stroke-dasharray="5 4"/>')
    s.text(LEFT + 200, 770, "optional or protective", size=11.5, color="muted")
    s.add(f'<rect x="{LEFT + 360}" y="760" width="22" height="12" rx="3" fill="none" stroke="{theme["yellow"]}" stroke-width="1.6"/>')
    s.text(LEFT + 390, 770, "leaves the server", size=11.5, color="muted")
    return s.render()


def main() -> None:
    for name, theme in THEMES.items():
        path = OUT / f"architecture-{name}.svg"
        path.write_text(draw(theme), encoding="utf-8")
        print(path.relative_to(OUT.parents[1]))


if __name__ == "__main__":
    main()
