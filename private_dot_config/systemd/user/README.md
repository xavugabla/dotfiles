# User systemd environment

`dev-git-fetch.service.tmpl` and `~/.config/environment.d/10-dev-path.conf`
share one source of truth:

- `.chezmoitemplates/dev-env-policy.tmpl` for PATH order
- `.chezmoitemplates/onepassword-agent.tmpl` for `SSH_AUTH_SOCK`

Path order remains: mise shims first, then user bins, then system paths.

For services that need secrets, prefer a service-owned env file:

```ini
[Service]
EnvironmentFile=%h/.config/SERVICE/SERVICE.env
```

Create those files manually or with a trusted service-specific script, set them
to mode `600`, and keep them out of git. Do not make user services depend on
`op inject` during startup.
