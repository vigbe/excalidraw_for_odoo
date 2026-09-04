# excalidraw_for_odoo

Excalidraw whiteboard embedded as a native Odoo 18 Community application.

The vendored library (`@excalidraw/excalidraw` 0.18.1, MIT) plus its fonts are
bundled inside the module with esbuild, so the editor works fully offline and
behind proxies — no external CDN is contacted.

## Features

- Dedicated **Excalidraw** app: list of drawings + full editor form.
- Hand-drawn style shapes, arrows, freedraw, text, images and libraries.
- Scenes stored as standard Excalidraw JSON (`scene_data`) — round-trip
  compatible with `.excalidraw` files (import/export from the editor menu).
- Automatic JPEG preview (`preview_image`) generated in the browser for list
  thumbnails.
- Editor UI localized from the Odoo user language and themed light/dark
  from the webclient color scheme.
- Chatter + activities (`mail.thread`, `mail.activity.mixin`).
- Security: `User` group (create/edit) and `Manager` group (also delete),
  using classic security groups (category + implied groups).

## Installation

The module directory is a standalone git repository (like every addon in this
workspace). Register it in your Odoo addons path and install **Excalidraw for
Odoo** from the Apps menu (developer mode may be needed for non-store apps).

Dependencies: `web`, `mail` (Odoo 18 Community).

After installing, grant the *Excalidraw / User* (and optionally
*Excalidraw / Manager*) group to the users who need the tool.

## Technical notes

- `static/lib/excalidraw/` contains the esbuild bundle
  (`excalidraw.vendor.js` + code-split chunks) plus the `fonts/` tree.
- The bundle is **not** registered in `web.assets_backend`; it is loaded
  through a native dynamic `import()` in
  `static/src/js/excalidraw_loader.js` so its relative chunk URLs resolve.
- Fonts resolve through `window.EXCALIDRAW_ASSET_PATH` pointing at the
  module static folder.
- The field widget `excalidraw_canvas` (`excalidraw.drawing.scene_data`)
  mounts the React editor inside the OWL form view; in readonly mode the
  stored preview is shown instead.

Rebuilding the vendor bundle:

```bash
npm i @excalidraw/excalidraw@0.18.1 react@18.3.1 react-dom@18.3.1 esbuild
cat > excalidraw.vendor.js <<'JS'
export * from "@excalidraw/excalidraw";
export * as React from "react";
export * as ReactDOMClient from "react-dom/client";
JS
npx esbuild excalidraw.vendor.js --bundle --format=esm --minify --splitting \
  --target=es2020 --legal-comments=external --outdir=static/lib/excalidraw
cp node_modules/@excalidraw/excalidraw/dist/prod/fonts -R static/lib/excalidraw/fonts
cp node_modules/@excalidraw/excalidraw/dist/prod/index.css static/lib/excalidraw/excalidraw.css
```

## Licenses

- Module code: LGPL-3.
- Vendored assets: `@excalidraw/excalidraw` (MIT), `react` / `react-dom`
  (MIT) — notices kept in `static/lib/excalidraw/*.LEGAL.txt`,
  `LICENSE-excalidraw` and `LICENSE-react`.

## Roadmap

- Real-time multi-user collaboration (requires a collaboration backend).
- Optional embedding of drawings into arbitrary records via smart buttons.
