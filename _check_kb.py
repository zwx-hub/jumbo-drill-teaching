# -*- coding: utf-8 -*-
import json, re, os
p = r"C:\Users\zwxzw\Doubao\chats\2026-10-24\new-chat-2\jumbo-drill\jumbo_kb.js"
if not os.path.exists(p):
    print("MISSING")
    raise SystemExit
size = os.path.getsize(p)
s = open(p, encoding="utf-8").read()
start = s.index("[")
end = s.rindex("]")
body = s[start+1:end]
count = body.count('{"k"')
# 校验：抽前 2 条解析
import json as J
first_rows = [r for r in re.findall(r'\{"k":\[.*?\],"q":".*?","a":".*?"\}', body[:8000])]
print("bytes=%d count=%d sample_rows=%d" % (size, count, len(first_rows)))
for r in first_rows[:3]:
    try:
        o = J.loads(r)
        print("ok:", o["q"][:40], "->", o["a"][:30])
    except Exception as e:
        print("BAD ROW:", e, r[:80])
# 验证 JS 语法层面：函数定义存在
for key in ["window.JUMBO_KB", "buildKBIndex", "kbAnswer"]:
    print(key, "present" if key in s else "MISSING")
