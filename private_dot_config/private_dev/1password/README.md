# 1Password Service Templates

Create one template per service:
- `SERVICE.env.tpl`: an `op inject` template that renders to an env file.
- `SERVICE.target`: optional destination path. If omitted, `dev secrets sync`
  writes to `~/.config/SERVICE/SERVICE.env`.

Examples:
- `central-api.env.tpl`
- `central-api.target`

After editing templates, run `dev secrets sync SERVICE`.
