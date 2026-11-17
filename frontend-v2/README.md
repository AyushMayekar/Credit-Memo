# Credit Memo UI v2

A self-contained frontend for the Credit Memo app with a minimal editorial monochrome interface.

This folder is intentionally separate from the existing `frontend/` application. The previous frontend, the backend, the PDF preview route, and the backend PDF template have not been modified.

## Run locally

```bash
cd frontend-v2
npm install
npm run dev
```

Vite serves on `http://localhost:5173`. The API base defaults to:

```
http://127.0.0.1:8000/api/v1
```

Override it when needed:

```bash
VITE_API_BASE_URL=https://your-host/api/v1 npm run dev
```

Production build:

```bash
npm run build
npm run preview
```

## Backend connectivity

`src/api/client.js` contains the same endpoints, request methods, and payload shapes as the original frontend. Route paths, status strings, job polling, and handler flow are unchanged. The only visual additions are presentation-layer states (skeletons, empty/error panels, status chips, pipeline, and memo section index).

## Structure

```
src/
  api/client.js              API calls — same endpoints as the original app
  components/
    Layout.jsx               Top navigation shell and theme switch
    StatusChip.jsx           Shared status tone mapping
    StageProgress.jsx        Four-step workflow tracker + job progress
    ConfirmButton.jsx        Confirmation + loading wrapper
    ExtractionReview.jsx     Two-pane extraction validation
    CreditMemoViewer.jsx     Section index, collapsible memo sections
  context/UIContext.jsx      Theme, toasts, confirm dialog, loading overlay
  pages/
    Dashboard.jsx            Applications table + summary strip
    NewApplication.jsx       Two-panel assessment form
    Workspace.jsx            Assessment workspace and memo actions
  styles.css                 Tokens, primitives, components, responsive rules
```

## Design notes

- White / grey / black palette with one semantic accent for failure and destructive confirmation.
- Inter via Google Fonts, 1px borders, 4–8px radii, no gradients or clay shadows.
- Top navigation with a 2px active underline, 1280px content grid, and equal gutters.
- Responsive down to 390px; dark theme uses inverted monochrome tokens.
