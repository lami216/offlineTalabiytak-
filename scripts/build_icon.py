from pathlib import Path

from PIL import Image

SOURCE = Path("assets/Talabiytak-icon.png")
OUTPUT = Path("build-assets/Talabiytak.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    if not SOURCE.is_file():
        raise SystemExit("assets/Talabiytak-icon.png غير موجودة؛ لا يمكن إنشاء أيقونة مؤقتة.")
    with Image.open(SOURCE) as image:
        if image.format != "PNG":
            raise SystemExit("مصدر الأيقونة يجب أن يكون PNG صالحًا.")
        if image.width != image.height:
            raise SystemExit("مصدر الأيقونة يجب أن يكون مربعًا.")
        if image.width < 512:
            raise SystemExit("مصدر الأيقونة يجب أن يكون 512×512 على الأقل.")
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        else:
            image = image.copy()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        image.save(OUTPUT, sizes=SIZES)
    print(f"created {OUTPUT} with sizes: {', '.join(f'{w}x{h}' for w, h in SIZES)}")


if __name__ == "__main__":
    main()
