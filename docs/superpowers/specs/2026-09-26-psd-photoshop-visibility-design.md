# PSD Photoshop Visibility Design

## Goal

Export one PSD per page containing one full-canvas clean raster background and one editable text layer per translated bubble, with the document visibly rendering when opened by an independent PSD editor.

## Confirmed failure

The real `page_1.psd` canvas is `2243 x 3465`, but its clean layer bounds are `(-1122, -1733, 1121, 1732)`. `PhotoshopAPI.ImageLayer_8bit` positions image layers by their center; omitting `pos_x` and `pos_y` therefore centers the full-page image at the document origin instead of the canvas center.

## Design

Keep the existing PhotoshopAPI export architecture and make the smallest behavioral correction: create the clean image layer with `pos_x=width / 2` and `pos_y=height / 2`. Preserve the current layer model—editable text layers above one clean raster layer—and preserve the current fill-opacity and point-text changes until independent visual validation proves whether further changes are necessary.

The regression contract is reader-independent. `psd-tools`, not PhotoshopAPI's own reader, must report a visible, fully opaque, pixel-bearing clean layer that starts at `(0, 0)` and covers the complete canvas. PhotoshopAPI 0.9.1 quantizes layer centers to integers, so odd-sized canvases require one clipped padding pixel at the right and bottom to avoid losing source pixels.

## Visual verification

Generate the real `workspace/psd-verify` page through `export_page_psd`, open the resulting PSD in Photopea through browser automation, and capture a screenshot showing:

- the manga page visibly fills the document canvas;
- one clean background layer exists;
- four editable text layers exist above it;
- translated text is visible in multiple bubble positions.

Also export/render the document through an independent parser and inspect the rendered image locally. Photopea is the available Photoshop-compatible editor in this environment; Adobe Photoshop itself is not installed, so Adobe-specific acceptance remains a final human smoke check rather than a claim made by automation.

## Acceptance criteria

1. The new regression test fails before the production change because the clean layer has negative bounds.
2. The same test passes after the production change and reports full-canvas bounds.
3. All PSD export tests pass without warnings treated as success criteria.
4. The real page PSD contains exactly one clean pixel layer and one editable type layer for every non-empty rendered translation.
5. An independent renderer opens the PSD and visibly displays the page and translated text layers; an independent editor is additionally attempted and any environment-level block is reported explicitly.
6. The captured visual is consistent with `final/page_1_final.png`: full clean page plus multiple translated bubbles.
7. Repository checks pass, or any unrelated pre-existing failure is reported verbatim and not hidden.

## Non-goals

- Replacing PhotoshopAPI.
- Implementing a custom PSD text engine.
- Redesigning manga typesetting.
- Claiming Adobe Photoshop verification without running Adobe Photoshop.
