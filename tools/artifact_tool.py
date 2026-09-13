import re
from typing import Literal

ArtifactType = Literal["jsx", "html", "svg", "md", "mermaid"]

BABEL_CDN = "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.2/babel.min.js"
REACT_CDN = "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"
REACTDOM_CDN = "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"
MERMAID_CDN = "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.6.1/mermaid.min.js"


class ArtifactTool:
    """
    Structured output renderer.
    Tags: <artifact type='jsx|html|mermaid|svg|md'>
    JSX via @babel/standalone. HTML in sandboxed iframe.
    """

    async def render(self, type: ArtifactType, content: str, title: str = "") -> dict:
        """Render content as a typed artifact."""
        type = type.lower().strip()

        renderer = {
            "jsx":      self._render_jsx,
            "html":     self._render_html,
            "svg":      self._render_svg,
            "md":       self._render_md,
            "mermaid":  self._render_mermaid,
        }.get(type)

        if not renderer:
            return {"error": f"Unknown artifact type: {type}. Valid: jsx, html, svg, md, mermaid"}

        output = renderer(content, title)
        return {
            "type": type,
            "title": title,
            "rendered": output,
            "raw": content,
        }

    def _render_jsx(self, content: str, title: str) -> str:
        return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8"/>
  <title>{title or 'Artifact'}</title>
  <script src="{REACT_CDN}"></script>
  <script src="{REACTDOM_CDN}"></script>
  <script src="{BABEL_CDN}"></script>
</head><body>
  <div id="root"></div>
  <script type="text/babel">
    {content}
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(<App />);
  </script>
</body></html>"""

    def _render_html(self, content: str, title: str) -> str:
        # Sandbox the HTML in an iframe-ready document
        if "<html" in content.lower():
            return content
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/><title>{title or 'Artifact'}</title></head>
<body>{content}</body></html>"""

    def _render_svg(self, content: str, title: str) -> str:
        if content.strip().startswith("<svg"):
            return content
        return f"<svg xmlns='http://www.w3.org/2000/svg'>{content}</svg>"

    def _render_md(self, content: str, title: str) -> str:
        """Return raw markdown — client renders it."""
        return content

    def _render_mermaid(self, content: str, title: str) -> str:
        return f"""<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8"/>
  <script src="{MERMAID_CDN}"></script>
</head><body>
  <div class="mermaid">{content}</div>
  <script>mermaid.initialize({{startOnLoad:true}});</script>
</body></html>"""

    def parse_tag(self, raw: str) -> list[dict]:
        """Extract <artifact type='...'> blocks from LLM output."""
        pattern = re.compile(
            r"<artifact\s+type=['\"](\w+)['\"][^>]*>(.*?)</artifact>",
            re.DOTALL | re.IGNORECASE
        )
        results = []
        for match in pattern.finditer(raw):
            results.append({
                "type": match.group(1),
                "content": match.group(2).strip(),
            })
        return results
