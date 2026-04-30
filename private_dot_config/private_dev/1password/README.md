# Legacy 1Password Service Templates

These templates are optional compatibility files. They are not part of the
default local-dev, service, CI, or Cloud Run secret path.

Create one template per service:
- `SERVICE.env.tpl`: an `op inject` template that renders to an env file.
- `SERVICE.target`: optional destination path. If omitted, `dev secrets render-op`
  writes to `~/.config/SERVICE/SERVICE.env`.

Examples:
- `central-api.env.tpl`
- `central-api.target`

After editing templates, render explicitly with:

```bash
dev secrets render-op SERVICE
```

`dev secrets sync SERVICE` intentionally prints guidance instead of running
`op inject`. Use `dev secrets sync --legacy-op-inject SERVICE` only when you
want the old behavior.
