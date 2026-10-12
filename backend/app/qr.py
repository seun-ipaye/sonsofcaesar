import io

import segno


def qr_png(code: str, scale: int = 10) -> bytes:
    """Black-on-white QR (scanners read dark-on-light most reliably)."""
    buf = io.BytesIO()
    segno.make(code, error='m').save(buf, kind='png', scale=scale, border=2, dark='#000', light='#fff')
    return buf.getvalue()


def qr_svg(code: str) -> bytes:
    buf = io.BytesIO()
    segno.make(code, error='m').save(buf, kind='svg', scale=10, border=2, dark='#000', light='#fff', xmldecl=False)
    return buf.getvalue()
