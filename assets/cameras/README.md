# Camera images

When a question names a camera listed here, its picture opens in a panel on the
right of the chat. Cameras not listed here simply show no picture.

## Adding a camera

1. Put the image in this folder (`.jpg`, `.jpeg`, `.png` or `.webp`).
2. Add an entry to `cameras.json`:

```json
[
  {
    "name": "Sony a6700",
    "file": "sony-a6700.jpg",
    "aliases": ["ilce-6700"]
  },
  {
    "name": "Canon EOS R5",
    "file": "canon-r5.jpg"
  }
]
```

| Field     | Required | What it does |
|-----------|----------|--------------|
| `name`    | yes      | Full model name, brand first. Shown under the picture, and matched in questions. |
| `file`    | yes      | The image's file name in this folder. |
| `aliases` | no       | Extra spellings people type. |

Changes are picked up on the next question; no restart needed. If the file has
a mistake, a warning appears at the bottom of the sidebar.

## What already matches without aliases

From `"name": "Canon EOS R5"` the app also recognises `eos r5` and `r5`, in any
case and with or without spaces or hyphens (`R5`, `r-5`). It also folds these
spellings together:

- `α6700`, `alpha 6700` → `a6700`
- `Mark II`, `mk2`, `mkII` → `II`, so `"name": "Nikon Z6 II"` matches "Z6 Mark 2"

A generation is a different camera: "R5 Mark II" does not show the R5 picture.
Give each generation its own entry.

Add an alias only for spellings outside those rules, such as a body code
(`ilce-6700`) or shorthand (`a7m4` for the a7 IV).

## Image tips

- Landscape product shots on a white or transparent background suit the panel best.
- The panel is 300px wide, so ~800px wide is plenty. Keep files under ~500 KB.
