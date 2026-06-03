"""Shared HTML helpers for human-readable Network Authority pages."""

from __future__ import annotations


OPERATOR_CONSOLE_CSS = """
        :root {
            color-scheme: dark;
            --bg: #0b0f14;
            --panel: #121922;
            --panel-strong: #17212d;
            --line: #2a3646;
            --text: #e7edf5;
            --muted: #9fb0c3;
            --accent: #6ee7b7;
            --accent-2: #7dd3fc;
            --warn: #facc15;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
        }
        a { color: inherit; }
        code {
            color: #bfdbfe;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            word-break: break-all;
        }
        .shell {
            width: min(1160px, calc(100% - 32px));
            margin: 0 auto;
            padding: 44px 0 56px;
        }
        .hero {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: linear-gradient(135deg, #111923 0%, #0e151d 58%, #13211d 100%);
            padding: clamp(24px, 5vw, 44px);
        }
        .kicker {
            display: inline-flex;
            gap: 8px;
            align-items: center;
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0;
            text-transform: uppercase;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 0 18px rgba(110, 231, 183, 0.85);
        }
        h1 {
            margin: 16px 0 12px;
            max-width: 780px;
            font-size: clamp(2.1rem, 6vw, 4.3rem);
            line-height: 1.04;
            letter-spacing: 0;
        }
        h2 {
            margin: 0;
            font-size: 1.05rem;
            letter-spacing: 0;
        }
        .lead {
            max-width: 800px;
            margin: 0;
            color: var(--muted);
            font-size: 1.05rem;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 28px;
        }
        .stat {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: rgba(18, 25, 34, 0.72);
            padding: 16px;
        }
        .stat span {
            display: block;
            color: var(--muted);
            font-size: 0.82rem;
        }
        .stat strong {
            display: block;
            margin-top: 4px;
            font-size: 1.2rem;
        }
        section { margin-top: 28px; }
        .section-head {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            align-items: end;
            margin-bottom: 12px;
        }
        .section-head p {
            margin: 0;
            color: var(--muted);
            font-size: 0.92rem;
        }
        .route-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
            gap: 12px;
        }
        .route-card {
            min-height: 150px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 17px;
            text-decoration: none;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
            transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
        }
        a.route-card:hover {
            border-color: var(--accent-2);
            background: var(--panel-strong);
            transform: translateY(-1px);
        }
        .route-card-static { cursor: default; }
        .method {
            width: fit-content;
            border: 1px solid rgba(125, 211, 252, 0.35);
            border-radius: 999px;
            padding: 2px 8px;
            color: var(--accent-2);
            font-size: 0.72rem;
            font-weight: 800;
        }
        .path {
            color: var(--text);
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-size: 0.92rem;
        }
        .route-card strong { font-size: 1rem; }
        .route-card span:last-child {
            color: var(--muted);
            font-size: 0.9rem;
        }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            border: 1px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
            background: var(--panel);
        }
        .data-table th,
        .data-table td {
            border-bottom: 1px solid var(--line);
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
        }
        .data-table th {
            color: var(--accent-2);
            background: var(--panel-strong);
            font-size: 0.9rem;
        }
        .data-table tr:last-child td { border-bottom: 0; }
        .empty-row td { color: var(--muted); }
        .notice {
            margin-top: 28px;
            border: 1px solid rgba(250, 204, 21, 0.36);
            border-radius: 8px;
            background: rgba(250, 204, 21, 0.08);
            padding: 16px;
            color: #f8eaa3;
        }
        .footer {
            margin-top: 28px;
            color: var(--muted);
            font-size: 0.9rem;
        }
        .action-link {
            display: inline-flex;
            align-items: center;
            min-height: 38px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--panel);
            padding: 8px 12px;
            color: var(--accent-2);
            text-decoration: none;
            font-weight: 700;
        }
        @media (max-width: 720px) {
            .shell { width: min(100% - 24px, 1160px); padding-top: 24px; }
            .section-head { display: block; }
            .section-head p { margin-top: 4px; }
        }
"""
