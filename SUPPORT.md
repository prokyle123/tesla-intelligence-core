# Support

## Start here

For installation and runtime problems:

1. Read [docs/INSTALL.md](docs/INSTALL.md).
2. Check [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
3. Check [docs/FAQ.md](docs/FAQ.md).
4. Search existing GitHub issues.

## Opening an issue

Use the repository issue forms when possible.

Please include:

- Tesla Intelligence Core version;
- Tesla model / model year;
- Raspberry Pi / host model;
- operating system;
- Tessie or TeslaMate;
- exact error text;
- relevant **redacted** service logs;
- what you expected;
- what happened instead.

## Privacy

Do not post:

- API tokens;
- MQTT passwords;
- full VINs;
- exact coordinates / addresses;
- private Tailscale hostnames;
- raw unredacted telemetry databases.

## Useful commands

```bash
ghost-ai status
systemctl status ghost-tesla-ai-web.service --no-pager
systemctl status ghost-tesla-ai-collector.service --no-pager
sudo journalctl -u ghost-tesla-ai-web.service -n 100 --no-pager
sudo journalctl -u ghost-tesla-ai-collector.service -n 100 --no-pager
```

## Security issues

Security-sensitive reports should follow [SECURITY.md](SECURITY.md), not a public troubleshooting issue.
