from seleniumbase import SB
import curl_cffi
import json
import os
import time
from pathlib import Path
from gchat_notifier import notify_critical, notify_final_status

TARGET_URL_PART = 'sales-api/salesApiLeadSearch'

# Just used to trigger a salesApiLeadSearch XHR while capturing cookies/headers -
# it does NOT need to match any campaign's actual search (any logged-in session
# loading any search results page produces the same auth headers). Campaign-
# specific search URLs live in campaigns.py -> CAMPAIGNS[...]['search_url'].
COOKIE_CAPTURE_SEARCH_URL = 'https://www.linkedin.com/sales/search/people?query=(spellCorrectionEnabled%3Atrue%2CrecentSearchParam%3A(doLogHistory%3Atrue)%2Cfilters%3AList((type%3ACOMPANY_HEADQUARTERS%2Cvalues%3AList((id%3A103644278%2Ctext%3AUnited%2520States%2CselectionType%3AINCLUDED))))%2Ckeywords%3Asupply%2520chain)'

# Master registry of physical LinkedIn accounts. Each gets its OWN browser profile
# (separate LinkedIn login) and its own saved cookies file. Add a new account here,
# then reference its name (this dict's key) from one or more campaigns'
# 'accounts' list in campaigns.py - that's what actually puts it to work.
ACCOUNTS = {
    'Ranganathan A': {'user_data_dir': './user_data/user_data_ranga', 'cookies_file': './cookies_files/ranga_cookies.json'},
    'Nandhini A': {'user_data_dir': './user_data/user_data_nandhini', 'cookies_file': './cookies_files/nandhini_cookies.json'},
    'Cynthia David': {'user_data_dir': './user_data/user_data_cynthia', 'cookies_file': './cookies_files/cynthia_cookies.json'},
    'Andrew Dreger': {'user_data_dir': './user_data/user_data_andrew', 'cookies_file': './cookies_files/andrew_cookies.json'},
    'Cindy Smith': {'user_data_dir': './user_data/user_data_cindy', 'cookies_file': './cookies_files/cindy_cookies.json'},
    'Anne Davis': {'user_data_dir': './user_data/user_data_anne', 'cookies_file': './cookies_files/anne_cookies.json'},
    'Kimberly Morrison': {'user_data_dir': './user_data/user_data_kimberly', 'cookies_file': './cookies_files/kimberly_cookies.json'},
    'David Bodiford': {'user_data_dir': './user_data/user_data_david', 'cookies_file': './cookies_files/david_cookies.json'},
}

# Resolve profile/cookie locations relative to this script, not the launch folder.
PROJECT_ROOT = Path(__file__).resolve().parent
for config in ACCOUNTS.values():
    for key in ('user_data_dir', 'cookies_file'):
        config[key] = str(PROJECT_ROOT / config[key])

INTERCEPT_SCRIPT = """
(function() {
  window.__capturedRequests = window.__capturedRequests || [];
  const TARGET = "%s";

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function(method, url) {
    this.__url = url; this.__method = method; this.__reqHeaders = {};
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function(header, value) {
    this.__reqHeaders[header] = value;
    return origSetHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    this.addEventListener('load', function() {
      if (this.__url && this.__url.includes(TARGET)) {
        window.__capturedRequests.push({
          url: this.__url,
          method: this.__method,
          requestHeaders: this.__reqHeaders
        });
      }
    });
    return origSend.apply(this, arguments);
  };
})();
""" % TARGET_URL_PART

def fetch_cookies(account):
    """Launch a real browser signed into `account`'s own LinkedIn Sales Nav profile
    (its own user_data_dir), capture live auth headers + cookies for the
    salesApiLeadSearch endpoint, and save them to that account's cookies_file.
    Returns the saved dict. `account` must be a key in ACCOUNTS."""
    config = ACCOUNTS[account]
    try:
        with SB(uc=True, user_data_dir=config['user_data_dir']) as sb:
            driver = sb.driver

            sb.uc_open_with_reconnect(COOKIE_CAPTURE_SEARCH_URL, reconnect_time=3)
            sb.sleep(3)

            print(f'[{account}] Complete login/2FA in the browser if prompted. Waiting up to 3 minutes for Sales Navigator search.')
            deadline = time.monotonic() + 180
            while '/sales/search/' not in driver.current_url:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Login was not completed. Saved cookies have not been changed.')
                sb.sleep(2)

            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": INTERCEPT_SCRIPT})
            driver.execute_script("window.location.reload();")
            sb.sleep(10)

            # --- JS-settable headers captured via XHR override ---
            captured = driver.execute_script("return window.__capturedRequests || [];")
            matches = [c for c in captured if TARGET_URL_PART in c["url"]]
            js_headers = matches[0]["requestHeaders"] if matches else {}
            matched_url = matches[0]["url"] if matches else None

            # --- Browser-standard values pulled dynamically (not hardcoded) ---
            user_agent = driver.execute_script("return navigator.userAgent;")
            language = driver.execute_script("return navigator.language;")
            platform = driver.execute_script("return navigator.platform;")

            # sec-ch-ua brand list — built dynamically from navigator.userAgentData if available
            ua_brands = driver.execute_script("""
                if (navigator.userAgentData && navigator.userAgentData.brands) {
                    return navigator.userAgentData.brands
                        .map(b => `"${b.brand}";v="${b.version}"`)
                        .join(', ');
                }
                return null;
            """)
            ua_mobile = driver.execute_script("""
                return navigator.userAgentData ? (navigator.userAgentData.mobile ? '?1' : '?0') : '?0';
            """)
            ua_platform = driver.execute_script("""
                return navigator.userAgentData ? navigator.userAgentData.platform : navigator.platform;
            """)

            referer = driver.current_url

            # --- Merge: browser-standard defaults, overridden/extended by JS-captured headers ---
            full_headers = {
                "accept": "*/*",
                "accept-language": f"{language},en;q=0.9",
                "priority": "u=1, i",
                "referer": referer,
                "sec-ch-ua": ua_brands or '"Not=A?Brand";v="99"',
                "sec-ch-ua-mobile": ua_mobile,
                "sec-ch-ua-platform": f'"{ua_platform}"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": user_agent,
            }
            full_headers.update(js_headers)  # csrf-token, x-li-*, x-restli-protocol-version etc. layer on top

            # --- Cookies ---
            all_cookies = driver.get_cookies()
            cookie_dict = {c["name"]: c["value"] for c in all_cookies}
            if not cookie_dict.get('li_at') or not matches:
                raise RuntimeError('Complete LinkedIn login and load Sales Navigator search before capturing this account')

            output = {
                "url": matched_url,
                "headers": full_headers,
                "cookies": cookie_dict,
            }

            # A captured XHR may itself have failed. Verify before replacing the
            # existing session file so a failed login cannot destroy it.
            with curl_cffi.Session() as probe:
                probe.headers.update(full_headers)
                probe.cookies.update(cookie_dict)
                result = probe.get(matched_url, timeout=30)
                if result.status_code != 200:
                    raise RuntimeError(f'Captured session was rejected (HTTP {result.status_code}); existing file unchanged')

            output_file = config['cookies_file']
            os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            print(f"[{account}] Saved to {output_file}")
            print(f"[{account}] Matched requests found: {len(matches)}")

            # if matches:
            #     notify_final_status(account, {'🍪 Cookies saved to': output_file, '📡 Auth headers captured': len(matches)})
            # else:
            #     notify_critical(account, 'No salesApiLeadSearch requests captured - login may have failed or the session is stale')

            return output
    except Exception as e:
        raise RuntimeError(f'Cookie capture failed for {account}: {e}') from e

def load_session(account, refresh=False):
    """Return a curl_cffi Session pre-loaded with `account`'s saved headers/cookies.
    Runs fetch_cookies(account) first if refresh=True or that account's cookies file
    doesn't exist yet, so callers never touch the cookies JSON directly - just
    `session = load_session('Ranganathan A')`."""
    cookies_file = ACCOUNTS[account]['cookies_file']
    if refresh or not os.path.exists(cookies_file):
        fetch_cookies(account)
    with open(cookies_file, 'r') as f:
        json_data = json.load(f)
    session = curl_cffi.Session()
    session.headers.update(json_data.get('headers', {}))
    session.cookies.update(json_data.get('cookies', {}))
    return session

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Capture a local LinkedIn browser session')
    parser.add_argument('--account', choices=list(ACCOUNTS), help='Capture just this account')
    args = parser.parse_args()
    for account in ([args.account] if args.account else ACCOUNTS):
        try:
            fetch_cookies(account)
        except Exception as e:
            print(f"[{account}] Cookie fetch failed: {e}")
