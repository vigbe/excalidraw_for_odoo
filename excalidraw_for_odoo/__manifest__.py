# Odoo __manifest__.py must be a bare dict literal (read via ast.literal_eval);
# the "useless/unused expression" warnings are unavoidable false positives,
# suppressed below for both ruff (B018) and Pyright.
# pyright: reportUnusedExpression=false
{  # noqa: B018
    "name": "Excalidraw for Odoo",
    "version": "18.0.1.0.0",
    "category": "Productivity",
    "summary": "Embedded Excalidraw whiteboard: draw diagrams and sketches inside Odoo",
    "description": """
Excalidraw for Odoo
===================

Embeds the Excalidraw whiteboard (https://excalidraw.com) as a first-class
Odoo application, fully self-hosted (no CDN required).

Features
--------
* Dedicated "Excalidraw" app with a list of drawings and a full editor form.
* Hand-drawn style diagrams: rectangles, arrows, text, freedraw, images...
* Scenes are persisted as editable JSON (excalidraw.drawing.scene_data).
* Automatic JPEG preview stored as attachment for list thumbnails.
* Built-in Excalidraw export dialog (PNG / SVG) and .excalidraw file import.
* Chatter + activities on drawings for team collaboration notes.
* Permission model: Users (read/write/create) and Managers (also delete).
* Vendored library: @excalidraw/excalidraw 0.18.1 (MIT) bundled with esbuild,
  fonts served locally via window.EXCALIDRAW_ASSET_PATH.

Roadmap (not included): real-time multi-user collaboration.
    """,
    "author": "Victor Bastías Escobar",
    "website": "https://vicbas.com",
    "support": "contacto@vicbas.com",
    "maintainer": "Victor Bastías Escobar",
    "license": "LGPL-3",
    "depends": [
        "web",
        "mail",
    ],
    "data": [
        "security/excalidraw_security.xml",
        "security/ir.model.access.csv",
        "views/excalidraw_drawing_views.xml",
    ],
    "images": [
        "static/description/thumbnail.png",
    ],
    "assets": {
        "web.assets_backend": [
            "excalidraw_for_odoo/static/src/scss/excalidraw.scss",
            "excalidraw_for_odoo/static/src/js/excalidraw_loader.js",
            "excalidraw_for_odoo/static/src/js/fields/excalidraw_canvas_field.js",
            "excalidraw_for_odoo/static/src/xml/excalidraw_canvas_field.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
