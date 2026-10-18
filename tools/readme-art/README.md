# README artwork

Original project artwork prepared with AI coding assistance on 14 October 2026. These illustrations show concepts, not measured research outputs or a live application. The animated cover runs twice and stops; the README also links to a still PNG. Both assets are local to this repository and require no external image host.

The source renderer uses Python 3.12, Pillow 12.3.0 and DejaVu fonts. The inline script metadata pins Pillow independently of the research project's unchanged uv lock. Font files are not redistributed. Supply a directory containing DejaVuSans.ttf, DejaVuSans-Bold.ttf, DejaVuSansMono.ttf and DejaVuSerif.ttf with `--font-dir` when the default Linux font directory is unavailable.

```bash
uv run --script tools/readme-art/render.py continuum-bench --output docs/assets/readme
```

Outputs are a 1440 x 570 still PNG and a 54-frame GIF with 150 ms per frame. Colours, layout, copy and motion are authored in the renderer. There are no third-party photos, university marks, model-generated images, benchmark traces or remote badges. Asset pixels may vary across font/Pillow versions; use the committed render for display. The renderer does not load models, create annotations or access a network service. Code follows the repository's Apache-2.0 licence; original covers follow its documentation CC BY 4.0 terms.
