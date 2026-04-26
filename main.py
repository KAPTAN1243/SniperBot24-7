import sys
import requests
import threading
import time
import queue
import string
import random
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return 'Bot is alive 24/7!'

def keep_alive():
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=8080))
    t.daemon = True
    t.start()

WEBHOOK_URL = 'https://discord.com/api/webhooks/1497368595968163850/278eP8w1R5BMDJmZBpOqcWJJoBOiRCMKOOUqT_eKUY8Q1Sl-8kXXJTJbuRMChzbO0OTA'
THREADS_COUNT = 50
PROXY_REFRESH_INTERVAL = 60
MAX_PROXY_FAILS = 1
TIMEOUT = 2.0
USE_PROXIES = True
WEBHOOK_INTERVAL = 0.5  # Her 0.5 saniyede 1 webhook

hits = misses = errors = ratelimits = total_checked = checks_per_second = current_cps = 0
start_time = None
proxy_lock = threading.Lock()
proxies_list = []
proxy_fail_count = {}
proxy_ping = {}
hit_usernames = []
webhook_queue = queue.Queue()

class AIOptimizer:
    @staticmethod
    def rank_proxies():
        global proxies_list
        with proxy_lock:
            good = [p for p in proxies_list
                    if proxy_fail_count.get(p, 0) < MAX_PROXY_FAILS
                    and proxy_ping.get(p, 0.5) < 2.0]
            good.sort(key=lambda p: proxy_ping.get(p, 1000))
            proxies_list = good

    @staticmethod
    def record_ping(p, t):
        if p is None: return
        with proxy_lock:
            proxy_ping[p] = (proxy_ping.get(p, t) + t) / 2

PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3000&country=all&ssl=all&anonymity=all',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt',
    'https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt',
]

def fetch_proxies_from_url(url):
    result = set()
    protocol = 'socks5' if 'socks5' in url.lower() else 'http'
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            for line in r.text.splitlines():
                p = line.strip()
                if p and ':' in p and len(p) < 30:
                    parts = p.split(':')
                    if len(parts) >= 2 and parts[-1].isdigit():
                        result.add(f'{protocol}://{p}')
    except: pass
    return result

def fetch_geonode():
    result = set()
    try:
        r = requests.get('https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc', timeout=10)
        if r.status_code == 200:
            for e in r.json().get('data', []):
                ip, port, protos = e.get('ip'), e.get('port'), e.get('protocols', [])
                if ip and port and protos:
                    proto = 'socks5' if 'socks5' in protos else ('socks4' if 'socks4' in protos else 'http')
                    result.add(f'{proto}://{ip}:{port}')
    except: pass
    return result

def fetch_all_proxies():
    all_p = set()
    all_p.update(fetch_geonode())
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in [ex.submit(fetch_proxies_from_url, u) for u in PROXY_SOURCES]:
            try: all_p.update(f.result(timeout=10))
            except: pass
    return list(all_p)

def load_proxies():
    global proxies_list, proxy_fail_count, proxy_ping
    online = fetch_all_proxies()
    with proxy_lock:
        proxies_list = list(set(online))
        proxy_fail_count = {}; proxy_ping = {}
    AIOptimizer.rank_proxies()
    total = len(proxies_list)
    print('[AI] ' + str(total) + ' proxy aktif.')
    return total

def get_proxy():
    with proxy_lock:
        if not proxies_list: return None
        top = max(1, len(proxies_list) // 5)
        return random.choice(proxies_list[:top])

def format_proxy(p):
    return {'http': p, 'https': p} if p else None

def mark_fail(p):
    if not p: return
    with proxy_lock:
        proxy_fail_count[p] = proxy_fail_count.get(p, 0) + 1
        proxy_ping[p] = proxy_ping.get(p, 1000) + 2.0

def mark_ok(p):
    if not p: return
    with proxy_lock: proxy_fail_count[p] = 0

def proxy_refresher():
    while True:
        time.sleep(PROXY_REFRESH_INTERVAL)
        try:
            new = fetch_all_proxies()
            with proxy_lock:
                ex = set(proxies_list)
                for p in new:
                    if p not in ex: proxies_list.append(p)
            AIOptimizer.rank_proxies()
        except: pass

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36',
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Origin': 'https://discord.com',
        'Referer': 'https://discord.com/register',
    }

sessions = {}
sessions_lock = threading.Lock()

def get_session(p):
    with sessions_lock:
        if p not in sessions:
            s = requests.Session()
            s.proxies = format_proxy(p)
            sessions[p] = s
        return sessions[p]

def check_username(username, proxy_str):
    url = 'https://discord.com/api/v9/unique-username/username-attempt-unauthed'
    t0 = time.time()
    try:
        if USE_PROXIES and proxy_str:
            r = get_session(proxy_str).post(url, json={'username': username}, headers=get_headers(), timeout=TIMEOUT)
        else:
            r = requests.post(url, json={'username': username}, headers=get_headers(), timeout=TIMEOUT)
        AIOptimizer.record_ping(proxy_str, time.time() - t0)
        if r.status_code == 200:
            return 'available' if not r.json().get('taken', True) else 'taken'
        elif r.status_code == 429: return 'ratelimit'
        else: return 'error'
    except:
        AIOptimizer.record_ping(proxy_str, 5.0)
        return 'error'

# ── SADE WEBHOOK: "username is available" ─────────────────────────────────────
def send_webhook(username):
    payload = {'content': username + ' is available'}
    for _ in range(3):
        try:
            r = requests.post(WEBHOOK_URL, json=payload, timeout=8)
            if r.status_code in (200, 204): return
            if r.status_code == 429:
                time.sleep(float(r.json().get('retry_after', 2)))
        except: time.sleep(2)

def webhook_dispatcher():
    """Webhook kuyrugundan surekli atar — durmaz"""
    while True:
        try:
            username = webhook_queue.get(timeout=5)
            if username:
                send_webhook(username)
                print('WEBHOOK -> ' + username)
            time.sleep(WEBHOOK_INTERVAL)
        except queue.Empty: continue
        except Exception as e:
            print('Webhook hata: ' + str(e))
            time.sleep(2)

def generate_all_usernames():
    out = set()
    L = string.ascii_lowercase
    D = string.digits

    for length in range(2, 5):
        for _ in range(3000):
            out.add(''.join(random.choice(D) for _ in range(length)))
    for length in range(5, 9):
        for _ in range(8000):
            out.add(''.join(random.choice(D) for _ in range(length)))
    for length in range(2, 6):
        for _ in range(5000):
            out.add(''.join(random.choice(L) for _ in range(length)))
    for _ in range(3000):
        c = random.choice(D + L)
        out.add(c * random.randint(2, 4))
    for _ in range(8000):
        n = ''.join(random.choice(D) for _ in range(2))
        a = ''.join(random.choice(L) for _ in range(2))
        out.add(n + a); out.add(a + n)
    for _ in range(10000):
        n = ''.join(random.choice(D) for _ in range(3))
        a = ''.join(random.choice(L) for _ in range(2))
        out.add(n + a); out.add(a + n)
    for _ in range(10000):
        n = ''.join(random.choice(D) for _ in range(4))
        a = ''.join(random.choice(L) for _ in range(2))
        out.add(n + a); out.add(a + n)
    for _ in range(3000):
        a = random.choice(L + D); b = random.choice(L + D)
        out.add(a + b + b + a)
        out.add(a + b + a + b)
    return list(out)

# ── SUREKLI FEEDER: q.join() yok, durmuyor ───────────────────────────────────
def username_feeder(q):
    """Nick uretip surekli kuyruga atar — hicbir zaman durmaz"""
    batch = 0
    while True:
        try:
            usernames = generate_all_usernames()
            random.shuffle(usernames)
            batch += 1
            print('Batch #' + str(batch) + ' -> ' + str(len(usernames)) + ' hedef kuyruga eklendi')
            for u in usernames:
                # Kuyruk doluysa bekle (memory tasarrufu)
                while q.qsize() > 80000:
                    time.sleep(1)
                q.put(u)
        except Exception as e:
            print('Feeder hata: ' + str(e))
            time.sleep(5)

def worker(q):
    global hits, misses, errors, ratelimits, total_checked, checks_per_second

    while True:
        try: username = q.get(timeout=5)
        except queue.Empty: continue
        if username is None: break

        proxy = get_proxy() if USE_PROXIES else None
        result = check_username(username, proxy)
        now = datetime.now().strftime('%H:%M:%S')

        if result == 'available':
            hits += 1; total_checked += 1; checks_per_second += 1
            hit_usernames.append(username)
            try:
                with open('hits.txt', 'a', encoding='utf-8') as f:
                    f.write(username + '\n')
            except: pass
            print('HIT: ' + username + ' | ' + now)
            webhook_queue.put(username)
            mark_ok(proxy)
        elif result == 'taken':
            misses += 1; total_checked += 1; checks_per_second += 1
            mark_ok(proxy)
        elif result == 'ratelimit':
            ratelimits += 1; checks_per_second += 1
            mark_fail(proxy); q.put(username); time.sleep(1)
        else:
            errors += 1; mark_fail(proxy); q.put(username)

        if total_checked % 50 == 0:
            AIOptimizer.rank_proxies()
        q.task_done()

def update_stats():
    global checks_per_second, current_cps
    while True:
        current_cps = checks_per_second; checks_per_second = 0
        elapsed = time.strftime('%H:%M:%S', time.gmtime(time.time() - start_time if start_time else 0))
        print('[STATS] Hits:' + str(hits) + ' Miss:' + str(misses) +
              ' Err:' + str(errors) + ' | ' + str(current_cps) + ' c/s | Uptime:' + elapsed)
        time.sleep(10)

def main():
    global start_time
    print('=== DISCORD USERNAME SNIPER v6.0 — SUREKLI MOD ===')

    keep_alive()
    print('Keep-alive server started on port 8080')

    if USE_PROXIES:
        load_proxies()
    else:
        print('Proxy disabled.')

    global THREADS_COUNT
    THREADS_COUNT = 50 if USE_PROXIES else 3
    print(str(THREADS_COUNT) + ' thread baslatiliyor...')

    start_time = time.time()

    # Arka plan servisleri
    threading.Thread(target=update_stats,       daemon=True).start()
    threading.Thread(target=proxy_refresher,    daemon=True).start()
    threading.Thread(target=webhook_dispatcher, daemon=True).start()

    # Is kuyrugu
    q = queue.Queue(maxsize=200000)

    # Worker'lar
    for _ in range(THREADS_COUNT):
        threading.Thread(target=worker, args=(q,), daemon=True).start()

    # Surekli feeder (q.join() yok — hic durmuyor)
    threading.Thread(target=username_feeder, args=(q,), daemon=True).start()

    print('Calisıyor... Bosta nick\'ler webhook\'a otomatik atilacak.')

    # Ana thread sadece canli tutar
    while True:
        time.sleep(60)

if __name__ == '__main__':
    main()
