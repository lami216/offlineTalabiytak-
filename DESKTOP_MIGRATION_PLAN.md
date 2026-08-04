# Desktop migration plan

## Audit
The original runtime used MongoDB in `app/database/mongo.py`, BSON identifiers and all five repository modules. ImageKit was isolated in `app/services/storage/imagekit.py`; import/product services upload and delete through that abstraction, while Excel previously downloaded delivery URLs with HTTP. External traffic was limited to MongoDB, ImageKit upload/delivery, and Excel image HTTP downloads. Deployment files (`env.example`, nginx, PM2) remain documentation for the separate web edition and are not packaged.

## Conversion
Desktop mode selects SQLite repositories and `LocalImageStorage`; templates, static files, FastAPI routes, image extraction, pricing, and business services remain shared. Resources must resolve through `_MEIPASS`. SQLite contains `schema_version`, `imports`, `imported_images`, `products`, `orders`, `order_items`, and `orphan_cleanup`, with text IDs, foreign keys, indexes, timestamps, image state, duplicate/link fields, ordering and expiry.

Images use `images/<sha256[0:2]>/<sha256[2:4]>/<sha256>.<verified extension>`. Only relative paths are stored. Runtime folders are database, images, logs and temp beneath platformdirs' user data location. No published data is copied or seeded.

## Installer pipeline
Install dependencies, test/lint, build the one-folder PyInstaller application, download and Authenticode-check Microsoft's offline WebView2 installer, compile Inno Setup, then smoke-test the output on Windows Sandbox. Updates replace only program files; data remains outside `{app}`.
