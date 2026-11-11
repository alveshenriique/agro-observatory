// Generated from src/atlas_da_lavoura/viz/identity.py by scripts/make_web_tokens.py. Do not edit by hand: run `uv run python scripts/make_web_tokens.py`.
export const tokens = {
  "fontFamily": "IBM Plex Sans",
  "fontStack": "\"IBM Plex Sans\", system-ui, sans-serif",
  "typeScaleRem": {
    "title": "1.4167rem",
    "subtitle": "1.1667rem",
    "panel_title": "1.0833rem",
    "label": "1rem",
    "small": "0.9167rem"
  },
  "themes": {
    "light": {
      "background": "#ffffff",
      "dry": "#895819",
      "wet": "#1a695f",
      "hot": "#67001f",
      "cold": "#4393c3",
      "neutral": "#9a9184",
      "text": "#1f1b16",
      "text_secondary": "#4d473f",
      "text_muted": "#6b6359",
      "grid": "#ece9e4",
      "sequential": [
        "#f2ede3",
        "#c1bcb2",
        "#969088",
        "#6e6961",
        "#49443d",
        "#241f19"
      ]
    },
    "dark": {
      "background": "#0d1117",
      "dry": "#a36c22",
      "wet": "#7cbab5",
      "hot": "#de8475",
      "cold": "#3379aa",
      "neutral": "#6e675d",
      "text": "#f2eee8",
      "text_secondary": "#cec7bc",
      "text_muted": "#a39b8f",
      "grid": "#222831",
      "sequential": [
        "#211d1a",
        "#47423e",
        "#6c6761",
        "#948e87",
        "#bfb9b0",
        "#f0eadf"
      ]
    }
  }
} as const;

export type Theme = keyof typeof tokens.themes;
