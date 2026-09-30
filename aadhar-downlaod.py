import sys
import os
import re
import base64
import requests
import uuid
import ddddocr
from io import BytesIO

# Configuration
BASE_URL = "https://tathya.uidai.gov.in"
CAPTCHA_URL = f"{BASE_URL}/audioCaptchaService/api/captcha/v3/generation"
OTP_URL = f"{BASE_URL}/unifiedAppAuthService/api/v2/generate/aadhaar/otp"
DOWNLOAD_URL = f"{BASE_URL}/downloadAadhaarService/api/aadhaar/download"

def run_download(eid, chat_id, mobile=None):
    # Session to keep cookies/session state
    session = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    # Proxy support — auto Indian proxy for Render deployment
    try:
        from proxy_manager import get_proxy_dict
        _proxy = get_proxy_dict()
        if _proxy:
            session.proxies.update(_proxy)
            print(f"[PROXY] Using proxy: {list(_proxy.values())[0]}")
    except Exception as _pe:
        print(f"[PROXY] Proxy setup skipped: {_pe}")
    
    request_id = str(uuid.uuid4())

    # Browser-like strict headers
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en_IN",
        "Content-Type": "application/json",
        "appid": "MYAADHAAR",
        "x-request-id": request_id,
        "Origin": "https://myaadhaar.uidai.gov.in",
        "Referer": "https://myaadhaar.uidai.gov.in/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Connection": "keep-alive"
    }

    print("--- STEP 1: Fetching Captcha ---")
    captcha_payload = {
        "captchaLength": "6", 
        "captchaType": "2", 
        "audioCaptchaRequired": True
    }
    
    max_captcha_retries = 10
    cap_txn_id = None
    captcha_val = None
    otp_txn_id = None
    last_server_msg = "Failed to send OTP after maximum retries. Please verify details and try again."
    attempt = 1
    captcha_attempts = 0
    max_captcha_attempts = 30
    while attempt <= max_captcha_retries and captcha_attempts < max_captcha_attempts:
        captcha_attempts += 1
        try:
            res_cap = session.post(CAPTCHA_URL, json=captcha_payload, headers=headers, timeout=30)
            res_cap.raise_for_status()
            try:
                cap_data = res_cap.json()
            except ValueError:
                raise Exception("Aadhaar Portal returned an invalid non-JSON page during captcha load. Gateway might be down.")
            
            if not cap_data or 'imageBase64' not in cap_data or 'transactionId' not in cap_data:
                raise Exception("UIDAI captcha generation failed. Invalid server response.")
            
            img_b64 = cap_data['imageBase64']
            cap_txn_id = cap_data['transactionId']

            # Solve captcha with ddddocr
            img_bytes = base64.b64decode(img_b64)
            if attempt >= 3:
                print(f"🔑 MANUAL CAPTCHA REQUIRED | {img_b64}")
                sys.stdout.flush()
                captcha_val = sys.stdin.readline().strip()
                if not captcha_val:
                    raise Exception("No manual captcha entered.")
            else:
                ocr = ddddocr.DdddOcr(show_ad=False)
                res = ocr.classification(img_bytes)
                captcha_val = str(res or '').strip()
                captcha_val = re.sub(r'[^a-zA-Z0-9]', '', captcha_val)
                
                if len(captcha_val) != 6:
                    print(f"⚠️ [OCR] Rejected noisy read '{captcha_val}' (Length {len(captcha_val)} != 6). Fetching new captcha...")
                    continue
                
            print(f"Decoded Captcha: {captcha_val}")
            
            # Request OTP
            # Detect EID type: S-prefix = Session EID, numeric = actual EID
            id_type = "eid"
            if str(eid).upper().startswith('S'):
                id_type = "eid"  # Still use "eid" but log it
                print(f"ℹ️ Session EID detected (S-prefix): {eid}, idType={id_type}")
            
            otp_payload = {
                "eidNumber": eid,
                "idType": id_type,
                "captchaTxnId": cap_txn_id,
                "captchaValue": captcha_val,
                "resendOTP": False,
                "transactionId": request_id
            }
            # Include mobile number if available — ensures OTP goes to correct number
            if mobile:
                otp_payload["mobileNumber"] = str(mobile)

            res_otp = session.post(OTP_URL, json=otp_payload, headers=headers, timeout=45)
            try:
                otp_data = res_otp.json()
            except ValueError:
                raise Exception("Aadhaar Portal returned an invalid non-JSON page during OTP request. Gateway might be down.")

            if otp_data.get('status') == "Success":
                mobile_hint = otp_data.get('mobileNo') or otp_data.get('mobile') or (otp_data.get('responseData') or {}).get('mobileNumber') or 'unknown'
                print(f"✅ OTP Sent Successfully! OTP going to: {mobile_hint} | Full Response: {otp_data}")
                otp_txn_id = otp_data.get('txnId') or otp_data.get('transactionId') or otp_data.get('otpTxnId') or (otp_data.get('responseData') or {}).get('otpTxnId')
                if not otp_txn_id:
                    print(f"⚠️ OTP txnId missing in response: {otp_data}")
                    raise Exception("OTP sent but txnId not found in response.")
                break
            else:
                msg = otp_data.get('message') or (otp_data.get('responseData') or {}).get('message') or 'OTP generation failed'
                print(f"Server Response Attempt {attempt}: {msg} | Full JSON: {otp_data}")
                if msg:
                    last_server_msg = msg
                if msg and "technical difficulties" in msg.lower():
                    print(f"⚠️ [RETRY] Technical difficulties on attempt {attempt}. Waiting 5s before retry...")
                    import time as _time; _time.sleep(5)
                    # Don't raise - let retry loop continue with fresh captcha
                    attempt += 1
                    continue
                if msg and ("exceeded" in msg.lower() or "permissible limit" in msg.lower() or "retry after" in msg.lower()):
                    raise Exception(f"⛔ OTP Limit Exceeded! UIDAI ne is number ke liye OTP block kar diya hai. Kripya 20-30 minutes baad try karein. ||| Real Server Response: {msg}")
                # Captcha issue, loop continues to retry
                attempt += 1
        except Exception as ex:
            if attempt == max_captcha_retries or captcha_attempts == max_captcha_attempts:
                raise Exception(f"Failed to solve captcha / send OTP after retries: {ex}")

    if not otp_txn_id:
        raise Exception(last_server_msg)

    # Prompt for OTP
    print("\n" + "="*60)
    print("🔑 ENTER THE OTP RECEIVED ON YOUR REGISTERED MOBILE")
    sys.stdout.flush()
    otp_code = sys.stdin.readline().strip()
    print("="*60)

    if not otp_code:
        raise Exception("No OTP entered.")

    download_payload = {
        "eid": eid,
        "mask": False,
        "otp": otp_code,
        "otpTxnId": otp_txn_id
    }

    # Add transactionId in headers specifically for the download endpoint
    download_headers = headers.copy()
    download_headers["transactionId"] = request_id

    print("Downloading Aadhaar PDF from UIDAI secure server...")
    res_dl = session.post(DOWNLOAD_URL, json=download_payload, headers=download_headers, timeout=60)
    
    print(f"⬇️ Download HTTP Status: {res_dl.status_code}")
    
    try:
        dl_data = res_dl.json()
    except ValueError:
        raise Exception(f"Download portal returned non-JSON response. HTTP {res_dl.status_code}. Response: {res_dl.text[:200]}")

    print(f"⬇️ Download Server Response: {str(dl_data)[:500]}")

    # Specific error: DEA_NET_OTP_ERR_001 = OTP invalid/expired (UIDAI disguises as "technical difficulties")
    err_code = dl_data.get('errorCode', '')
    if err_code == 'DEA_NET_OTP_ERR_001':
        raise Exception("❌ OTP Galat Ya Expired! UIDAI ne OTP reject kar diya. Kripya naya OTP mangayein. ||| errorCode: DEA_NET_OTP_ERR_001")

    # Flexible success check — handle both string and integer status
    dl_status = dl_data.get('status', '')
    is_success = (str(dl_status).lower() in ['success', '1', '0']) or (dl_status == 1) or (dl_status == 0 and dl_data.get('data'))

    if is_success and dl_data.get('data') and dl_data['data'].get('aadhaarPdf'):
        pdf_b64 = dl_data['data']['aadhaarPdf']
        
        # Decode base64 PDF
        pdf_bytes = base64.b64decode(pdf_b64)
        
        # Save to cracked_aadhar folder
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cracked_dir = os.path.join(script_dir, "cracked_aadhar")
        os.makedirs(cracked_dir, exist_ok=True)
        file_path = os.path.join(cracked_dir, f"Aadhaar_{chat_id}.pdf")
        
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)
            
        print(f"\n========================================")
        print(f"🎉 SUCCESS! Aadhaar PDF Downloaded Successfully!")
        print(f"📁 Saved as: {file_path}")
        print(f"========================================")
    else:
        # Extract real error from UIDAI response
        error_msg = (
            dl_data.get('statusMessage')
            or (dl_data.get('errorDetails') or {}).get('messageEnglish')
            or (dl_data.get('responseData') or {}).get('message')
            or dl_data.get('message')
            or dl_data.get('errorCode')
            or f'Download failed. Full response: {str(dl_data)[:300]}'
        )
        raise Exception(f"Download failed: {error_msg}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        EID = sys.argv[1]
        CHAT_ID = sys.argv[2]
        MOBILE = sys.argv[3] if len(sys.argv) >= 4 else None
    else:
        print("Usage: python aadhar-downlaod.py <EID> <CHAT_ID> [MOBILE]")
        sys.exit(1)
        
    try:
        run_download(EID, CHAT_ID, MOBILE)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)
