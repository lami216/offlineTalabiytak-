# Release checklist

- Set version/publisher/icon centrally and synchronize installer/tag version.
- Run pytest, ruff check, ruff format check and git diff check.
- Inspect build for `.env`, URI, keys, databases, images and sample customer data.
- Verify Microsoft's WebView2 Authenticode signature and retain its redistribution notice.
- Download the `Talabiytak-Windows-Installer` artifact and complete the clean-machine checklist.
- Record SHA-256 of the tested installer and publish only that artifact.
