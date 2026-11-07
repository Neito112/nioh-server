"""
VietQR Bank Generator Tool (Tạo Mã QR Ngân Hàng Việt Nam)
-----------------------------------------------------------
Hỗ trợ tạo link ảnh mã QR chuẩn Napas 247 VietQR cho tất cả ngân hàng Việt Nam
(Vietcombank, MB Bank, Techcombank, BIDV, VietinBank, VPBank, ACB, v.v.)
"""

import urllib.parse
import logging

logger = logging.getLogger("xiaozhivn.tools.bank_qr")

BANK_MAP = {
    "vcb": "vietcombank",
    "vietcombank": "vietcombank",
    "mb": "mbbank",
    "mbbank": "mbbank",
    "mb bank": "mbbank",
    "tcb": "techcombank",
    "techcombank": "techcombank",
    "bidv": "bidv",
    "ctg": "vietinbank",
    "vietinbank": "vietinbank",
    "acb": "acb",
    "vpb": "vpbank",
    "vpbank": "vpbank",
    "tpb": "tpbank",
    "tpbank": "tpbank",
    "hdb": "hdbank",
    "hdbank": "hdbank",
    "shb": "shb",
    "sacombank": "sacombank",
    "vib": "vib",
    "msb": "msb",
    "ocb": "ocb",
    "seabank": "seabank",
    "lpbank": "lpbank",
    "lienvietpostbank": "lpbank"
}


def generate_vietnam_bank_qr(bank: str, account_number: str, amount: int = 0, description: str = "", account_name: str = "") -> dict:
    """
    Tạo link ảnh mã QR thanh toán ngân hàng Napas 247 VietQR.
    """
    clean_bank = bank.strip().lower()
    bank_code = BANK_MAP.get(clean_bank, clean_bank)
    clean_acc = "".join(c for c in account_number if c.isalnum())

    if not clean_acc:
        return {
            "success": False,
            "message": "Số tài khoản ngân hàng không hợp lệ."
        }

    # Xây dựng URL chuẩn VietQR
    base_url = f"https://img.vietqr.io/image/{bank_code}-{clean_acc}-compact2.png"
    params = {}
    if amount and int(amount) > 0:
        params["amount"] = str(int(amount))
    if description:
        params["addInfo"] = description.strip()
    if account_name:
        params["accountName"] = account_name.strip()

    query_str = urllib.parse.urlencode(params)
    qr_image_url = f"{base_url}?{query_str}" if query_str else base_url

    amt_str = f"{int(amount):,} VNĐ" if amount and int(amount) > 0 else "Tùy ý"
    summary = (
        f"Đã tạo mã QR thanh toán VietQR cho ngân hàng {bank_code.upper()}:\n"
        f"- Số tài khoản: {clean_acc}\n"
        f"- Số tiền: {amt_str}\n"
        f"- Nội dung: {description or 'Không có'}\n"
        f"Mã QR sẵn sàng quét thanh toán."
    )

    return {
        "success": True,
        "bank": bank_code,
        "account_number": clean_acc,
        "amount": amount,
        "description": description,
        "qr_image_url": qr_image_url,
        "summary": summary
    }
