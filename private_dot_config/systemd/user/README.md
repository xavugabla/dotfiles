# User systemd environment

`dev-git-fetch.service` carries the same PATH policy as the shell templates:
mise shims first, then user bins, then system paths. It also points
`SSH_AUTH_SOCK` at the stable 1Password SSH agent socket.

For services that need secrets, prefer a service-owned env file:

```ini
[Service]
EnvironmentFile=%h/.config/SERVICE/SERVICE.env
```

Create those files manually or with a trusted service-specific script, set them
to mode `600`, and keep them out of git. Do not make user services depend on
`op inject` during startup.
