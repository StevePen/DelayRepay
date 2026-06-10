Run python3 hsp_delay_job.py
  python3 hsp_delay_job.py
  shell: /usr/bin/bash -e {0}
  env:
    HSP_EMAIL: ***
    HSP_PASSWORD: 
    TELEGRAM_BOT_TOKEN: ***
    TELEGRAM_CHAT_ID: ***
    SUPABASE_URL: ***
    SUPABASE_SERVICE_KEY: ***
    TEST_MODE: false
Checking commute for 2026-06-09


Morning into work (NFL to LBG):
  CLAIMABLE: 16 min late (due 0826, arrived 0842)
  Operator: Thameslink, claim here if this was your train:
  https://www.thameslinkrailway.com/help-and-support/delay-repay
Traceback (most recent call last):
  File "/home/runner/work/DelayRepay/DelayRepay/hsp_delay_job.py", line 311, in <module>
    run()
  File "/home/runner/work/DelayRepay/DelayRepay/hsp_delay_job.py", line 222, in run
    for rid in get_service_rids(leg, day_str):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/DelayRepay/DelayRepay/hsp_delay_job.py", line 113, in get_service_rids
    result = _hsp_post("serviceMetrics", {
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/DelayRepay/DelayRepay/hsp_delay_job.py", line 83, in _hsp_post
    with urllib.request.urlopen(req, timeout=30) as resp:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 515, in open
    response = self._open(req, data)
               ^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 532, in _open
    result = self._call_chain(self.handle_open, protocol, protocol +
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 1392, in https_open
    return self.do_open(http.client.HTTPSConnection, req,
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 1348, in do_open
    r = h.getresponse()
        ^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/http/client.py", line 1448, in getresponse
    response.begin()
  File "/usr/lib/python3.12/http/client.py", line 336, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/http/client.py", line 297, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/socket.py", line 707, in readinto
    return self._sock.recv_into(b)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/ssl.py", line 1252, in recv_into
    return self.read(nbytes, buffer)
           ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/ssl.py", line 1104, in read
    return self._sslobj.read(len, buffer)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
TimeoutError: The read operation timed out
Error: Process completed with exit code 1.
