// Generated from src/atlas_da_lavoura/viz/identity.py by scripts/make_web_tokens.py. Do not edit by hand: run `uv run python scripts/make_web_tokens.py`.
export const tokens = {
  "fontFamily": "IBM Plex Sans",
  "fontStack": "\"IBM Plex Sans\", system-ui, sans-serif",
  "typefaces": {
    "text": {
      "family": "IBM Plex Sans",
      "stack": "\"IBM Plex Sans\", system-ui, sans-serif",
      "features": [],
      "files": [
        {
          "weight": 400,
          "url": "/fonts/IBMPlexSans-Regular-Latin1.woff2"
        },
        {
          "weight": 700,
          "url": "/fonts/IBMPlexSans-Bold-Latin1.woff2"
        }
      ],
      "unicodeRange": "U+0000, U+000D, U+0020-007E, U+00A0-00A3, U+00A4-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2013-2014, U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030, U+2039-203A, U+2044, U+2074, U+20AC, U+2122, U+2212, U+FB01-FB02"
    },
    "titles": {
      "family": "IBM Plex Serif",
      "stack": "\"IBM Plex Serif\", Georgia, serif",
      "features": [],
      "files": [
        {
          "weight": 400,
          "url": "/fonts/IBMPlexSerif-Regular-Latin1.woff2"
        }
      ],
      "unicodeRange": "U+0020-007E, U+00A0-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2013-2014, U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030, U+2039-203A, U+2044, U+20AC, U+2122, U+2212, U+FB01-FB02"
    },
    "numbers": {
      "family": "IBM Plex Mono",
      "stack": "\"IBM Plex Mono\", ui-monospace, monospace",
      "features": [
        "ss04"
      ],
      "files": [
        {
          "weight": 400,
          "url": "/fonts/IBMPlexMono-Regular-Latin1.woff2"
        },
        {
          "weight": 600,
          "url": "/fonts/IBMPlexMono-SemiBold-Latin1.woff2"
        }
      ],
      "unicodeRange": "U+0020-007E, U+00A0-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2013-2014, U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030, U+2039-203A, U+2044, U+20AC, U+2122, U+2212, U+FB01-FB02"
    }
  },
  "displayNumber": {
    "role": "text",
    "weight": 700
  },
  "typeScaleRem": {
    "title": "1.4167rem",
    "subtitle": "1.1667rem",
    "panel_title": "1.0833rem",
    "label": "1rem",
    "small": "0.9167rem"
  },
  "webTypeScale": {
    "display": "clamp(3.5rem, 2.4773rem + 4.5455vw, 6rem)",
    "headline": "clamp(2.25rem, 1.8409rem + 1.8182vw, 3.25rem)",
    "brand": "clamp(1.25rem, 1.0966rem + 0.6818vw, 1.625rem)",
    "section": "clamp(1.5rem, 1.2955rem + 0.9091vw, 2rem)",
    "stat": "clamp(1.75rem, 1.4432rem + 1.3636vw, 2.5rem)",
    "deck": "clamp(1.125rem, 1.0483rem + 0.3409vw, 1.3125rem)",
    "body": "clamp(1rem, 0.9744rem + 0.1136vw, 1.0625rem)",
    "meta": "clamp(0.8125rem, 0.7869rem + 0.1136vw, 0.875rem)"
  },
  "themes": {
    "light": {
      "background": "#fcfbf9",
      "band": "#efebe2",
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
      "background": "#13110e",
      "band": "#1f1b16",
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
