#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三臂凿岩台车 3D 教学模型 —— 本地前后端交互服务器
================================================================
运行方式：
  方式一：双击 start_server.bat
  方式二：命令行执行  python server.py
启动后在浏览器打开： http://127.0.0.1:8000

功能：
  · 静态托管同目录下的 index.html（教学主页面）；旧版 三臂凿岩台车3D交互.html 仍可访问
  · REST API：
      GET  /api/health        健康检查（前端用于探测服务端是否可用）
      GET  /api/parts         部件清单（服务端权威数据，27 项）
      GET  /api/params        技术参数（钻臂 DJ3G / 凿岩机 HC95SA / 推进梁 / 作业平台）
      GET  /api/knowledge     知识要点（结构/原理/装配/维护）
      GET  /api/interactions  学习数据统计
      POST /api/interactions  上报一次学习行为 {action, partId?, ms?, ts?}
      POST /api/chat          AI 教学助教：把对话转发到 DeepSeek API（Key 读取自
                              同目录 deepseek_key.txt 或环境变量 DEEPSEEK_API_KEY，
                              Key 只存在于服务端，不会下发到浏览器）
  · 学习行为持久化到 learning_state.json（部件点击排行 / 演示次数 / 学习时长）
  · 已开启 CORS：前端页面部署到 GitHub Pages 等静态站点后，仍可调用本服务上报数据
纯 Python 标准库实现，无需安装任何第三方依赖。
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT, "learning_state.json")
HOST, PORT = "127.0.0.1", 8000
START_TIME = time.time()
LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# DeepSeek AI 教学助教（本地代理：浏览器 → /api/chat → DeepSeek）
# Key 从 deepseek_key.txt（已加入 .gitignore，不会入库）或环境变量读取
# ---------------------------------------------------------------------------
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_MAX_TOKENS = 2048
KEY_FILE = os.path.join(ROOT, "deepseek_key.txt")


def deepseek_key():
    """读取 DeepSeek API Key：优先环境变量，其次同目录 deepseek_key.txt。"""
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def forward_chat(messages, model=None, max_tokens=DEEPSEEK_MAX_TOKENS):
    """把 messages 转发到 DeepSeek，返回 (结果字典, 错误消息)。"""
    key = deepseek_key()
    if not key:
        return None, ("未配置 DeepSeek API Key：请在 server.py 同目录创建 "
                      "deepseek_key.txt 并写入你的 Key（该文件已被 .gitignore 忽略，"
                      "不会上传到 GitHub），或设置环境变量 DEEPSEEK_API_KEY。")
    payload = json.dumps({
        "model": model or DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": int(max_tokens or DEEPSEEK_MAX_TOKENS),
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        try:
            reply = data["choices"][0]["message"]["content"]
        except Exception:
            reply = ""
        return {"ok": True, "reply": reply, "model": data.get("model", model or DEEPSEEK_MODEL)}, None
    except urllib.error.HTTPError as e:
        err_code, err_msg = "", ""
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
            err = detail.get("error") or {}
            err_msg = err.get("message") or ""
            err_code = err.get("code") or ""
        except Exception:
            pass
        if e.code == 401:
            msg = "DeepSeek API Key 无效或未授权，请检查 deepseek_key.txt 中的 Key。"
        elif e.code == 402:
            msg = "DeepSeek 账户余额不足，请登录 DeepSeek 开放平台充值后重试。"
        elif e.code == 429:
            msg = "AI 请求过于频繁，请稍等片刻再试。"
        else:
            msg = "AI 服务暂时不可用（HTTP %d）%s" % (e.code, ("（" + err_msg + "）") if err_msg else "")
        return {"ok": False, "error": msg, "code": err_code}, None
    except Exception as e:
        return {"ok": False, "error": "AI 服务连接失败（%s）" % e.__class__.__name__}, None

# ---------------------------------------------------------------------------
# 服务端权威数据（前端在服务端模式下以此为准；本地模式下使用内置副本）
# ---------------------------------------------------------------------------
PARTS = [
    {"id": "chassis",  "name": "车体底盘",    "en": "Chassis",       "tag": "承载结构"},
    {"id": "wheels",   "name": "行走轮胎",    "en": "Wheel Drive",   "tag": "行走机构"},
    {"id": "cab",      "name": "驾驶室",      "en": "Operator Cabin","tag": "操纵系统"},
    {"id": "power",    "name": "动力·液压系统","en": "Power & Hydraulics", "tag": "动力单元"},
    {"id": "outrigger","name": "稳定支腿",    "en": "Stabilizer Leg","tag": "辅助装置"},
    {"id": "platform", "name": "作业平台",    "en": "Work Platform", "tag": "高空作业装置"},
    {"id": "boom1",    "name": "1号钻臂",     "en": "Drill Boom 1",  "tag": "工作装置·钻臂"},
    {"id": "arm1",     "name": "1号基本臂",   "en": "Base Arm 1",    "tag": "钻臂·基本臂"},
    {"id": "short1",   "name": "1号短臂",     "en": "Short Arm 1",   "tag": "钻臂·短臂"},
    {"id": "tbeam1",   "name": "1号T型梁",    "en": "T-Beam 1",      "tag": "钻臂·T型梁"},
    {"id": "feed1",    "name": "1号推进梁",   "en": "Feed 1",        "tag": "工作装置·推进"},
    {"id": "drill1",   "name": "1号凿岩机",   "en": "Rock Drill 1",  "tag": "工作装置·破岩"},
    {"id": "rod1",     "name": "1号钎杆钻头", "en": "Rod & Bit 1",   "tag": "工作装置·钻具"},
    {"id": "boom2",    "name": "2号钻臂",     "en": "Drill Boom 2",  "tag": "工作装置·钻臂"},
    {"id": "arm2",     "name": "2号基本臂",   "en": "Base Arm 2",    "tag": "钻臂·基本臂"},
    {"id": "short2",   "name": "2号短臂",     "en": "Short Arm 2",   "tag": "钻臂·短臂"},
    {"id": "tbeam2",   "name": "2号T型梁",    "en": "T-Beam 2",      "tag": "钻臂·T型梁"},
    {"id": "feed2",    "name": "2号推进梁",   "en": "Feed 2",        "tag": "工作装置·推进"},
    {"id": "drill2",   "name": "2号凿岩机",   "en": "Rock Drill 2",  "tag": "工作装置·破岩"},
    {"id": "rod2",     "name": "2号钎杆钻头", "en": "Rod & Bit 2",   "tag": "工作装置·钻具"},
    {"id": "boom3",    "name": "3号钻臂",     "en": "Drill Boom 3",  "tag": "工作装置·钻臂"},
    {"id": "arm3",     "name": "3号基本臂",   "en": "Base Arm 3",    "tag": "钻臂·基本臂"},
    {"id": "short3",   "name": "3号短臂",     "en": "Short Arm 3",   "tag": "钻臂·短臂"},
    {"id": "tbeam3",   "name": "3号T型梁",    "en": "T-Beam 3",      "tag": "钻臂·T型梁"},
    {"id": "feed3",    "name": "3号推进梁",   "en": "Feed 3",        "tag": "工作装置·推进"},
    {"id": "drill3",   "name": "3号凿岩机",   "en": "Rock Drill 3",  "tag": "工作装置·破岩"},
    {"id": "rod3",     "name": "3号钎杆钻头", "en": "Rod & Bit 3",   "tag": "工作装置·钻具"},
]

PARAMS = {
    "drill_boom": {
        "title": "钻臂 · DJ3G 型",
        "items": [
            ["大臂形式", "圆形臂，双三角自平行定位"],
            ["二节臂行程", "1600 mm"],
            ["钻臂补偿", "1600 mm"],
            ["推进补偿", "1800 mm"],
            ["推进翻转角度", "±180°"],
            ["大臂上扬角度", "65°"],
            ["大臂下俯角度", "30°"],
            ["大臂左右摆动角度", "±45°"],
        ],
        "note": "重型钻臂双三角支撑；关节采用膨胀轴设计；恒压+负载敏感控制，远程先导控制。",
    },
    "rock_drill": {
        "title": "凿岩机 · HC95SA",
        "items": [
            ["冲击功率", "21 kW"],
            ["冲击频率", "63 Hz"],
            ["冲击压力", "200 bar"],
            ["回转压力", "210 bar"],
            ["凿岩速度", "2.5 ~ 3 m/min"],
            ["钻孔直径", "43 ~ 102 mm"],
        ],
        "note": "液压凿岩机：高压油转化为冲击能与回转扭矩，冲击+回转联合破岩。",
    },
    "feed": {
        "title": "推进梁",
        "items": [
            ["钻孔深度", "5250 mm"],
            ["推进梁油缸行程", "1800 mm"],
            ["最大推进力", "23000 N"],
            ["梁体", "双底结构铝合金梁"],
            ["滑台", "上下底面耐磨不锈钢保护"],
            ["衬板", "配耐磨衬板，无金属直接接触"],
        ],
        "note": "推进梁主要包括：铝合金梁组件、油管卷盘组件、凿岩机托板、推进油缸组件、油管过板、中扶钎器、前扶钎器、尾部护板组件、托板滑块等。",
    },
    "platform": {
        "title": "作业平台",
        "items": [
            ["平台举升高度", "13646 mm"],
            ["平台摆动宽度", "16000 mm"],
            ["平台额定载重", "400 kg"],
            ["摆动角度", "±45°"],
            ["俯仰角度", "+60° / -35°"],
            ["服务平台延伸", "5000 mm"],
            ["工作篮尺寸", "1400 × 1200 mm"],
        ],
        "note": "应用：装药作业、撬毛作业、风管风筒安装、辅助作业、岩石加固作业、维修保养。",
    },
}

KNOWLEDGE = {
    "structure": {
        "title": "结构原理",
        "points": [
            "钻臂由 基本臂 → 短臂 → T型梁 三段构成，末端连接推进梁；基本臂内设导向筒与伸缩臂。",
            "大臂采用圆形臂、双三角自平行定位，专为承受大载荷设计，定位可靠准确。",
            "钻臂关节采用独特的膨胀轴设计，确保钻臂与油缸紧密连接，延长部件寿命。",
            "沿掘进方向看，三臂从左至右依次为 1 号臂、2 号臂、3 号臂；左臂推进梁在大臂左边，右臂推进梁在大臂右边。",
            "作业平台采用 连接座→转接件→基本臂→一级伸缩臂→二级伸缩臂→吊篮 的伸缩臂式结构。",
        ],
    },
    "working": {
        "title": "工作原理",
        "points": [
            "大臂举升为双油缸协同：上仰=两根油缸同时伸出；下俯=两根油缸同时缩回；摆动=一根伸出、一根缩回。",
            "翻转油缸可带动推进梁 ±180° 旋转；外插角油缸（0~90°）与摆动缸（±180°）配合可实现径向锚杆孔钻设。",
            "服务平台：随动油缸与吊篮油缸为随动关系（一个无杆腔连另一个有杆腔），始终保证吊篮处于水平状态。",
            "凿岩机通过推进/回退油缸+钢丝绳往复传动：前进钢丝绳一端连凿岩机托盘、另一端经动滑轮连推进梁尾端，驱动凿岩机前进钻孔。",
        ],
    },
    "assembly": {
        "title": "装配要点",
        "points": [
            "基本臂：胀销连接 6 处、螺栓连接 2 处、角度传感器 2 个、机械限位。",
            "短臂：胀销连接 6 处、螺栓连接 2 处、两个角度传感器。",
            "基本臂组件：大臂连接座、下部油缸连接座、大臂转接件、基本臂体、大臂伸缩油缸、导向筒、伸缩臂、下三角油缸。",
            "短臂组件：短臂铰接接头、上部油缸转接件、短臂转接件、短臂体、上三角油缸防护架、上三角油缸。",
            "T型梁组件：外插角油缸、翻转油缸转接件、T型梁、翻转油缸、外插角角度传感器。",
        ],
    },
    "maintain": {
        "title": "维护要点",
        "points": [
            "润滑点打黄油，每个班检查一次，如需要及时补充黄油。",
            "一级/二级伸缩臂调整垫、平台各铰点：每个班都需要检查润滑情况。",
            "前扶钎器、中扶钎器上的耐磨套磨损量较大时应及时更换。",
            "推进梁上下滑台底面均有耐磨不锈钢保护，配有耐磨衬板，没有金属与金属间的直接接触。",
        ],
    },
}


def _default_state():
    return {
        "server_start": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sessions": 0,
        "clicks": {},
        "demo_plays": 0,
        "explode_plays": 0,
        "view_resets": 0,
        "total_time_ms": 0,
        "events": [],
        "users": [],
        "assessments": [],
    }


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_state()


def save_state(state):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 学练考一体化：考核统计与个性化报告生成（教员后台 / 平台考核评估）
# ---------------------------------------------------------------------------
def _avg(lst):
    return round(sum(x.get("score", 0) for x in lst) / len(lst)) if lst else 0


def _dim_avg(recs):
    """统计各评分维度平均值，返回 {维度名: 平均分}。"""
    agg = {}
    for a in recs:
        dims = a.get("dims") or {}
        for k, v in dims.items():
            if k not in agg:
                agg[k] = [0, 0]
            agg[k][0] += v
            agg[k][1] += 1
    return {k: round(v[0] / v[1]) for k, v in agg.items()} if agg else {}


def teacher_summary(state):
    """教员后台学情概览汇总数据。"""
    assessments = state.get("assessments", [])
    users = state.get("users", [])
    practical = [a for a in assessments if a.get("type") == "practical"]
    formal = [a for a in assessments if a.get("type") == "formal"]
    return {
        "totalStudents": len(users),
        "totalAssess": len(assessments),
        "avgScore": _avg(assessments),
        "practicalAvg": _avg(practical),
        "formalAvg": _avg(formal),
        "assessments": assessments,
    }


REPORT_LABELS = {"personal": "个人学习报告", "class": "班级学情分析", "quality": "平台教学质量报告"}


def report_context(state, rtype, target):
    """把学员/班级/平台考核数据整理成文本上下文，供报告生成使用。"""
    assessments = state.get("assessments", [])
    users = state.get("users", [])
    lines = []
    if rtype == "personal":
        recs = [a for a in assessments if a.get("name") == target]
        u = next((x for x in users if x.get("name") == target), {})
        lines.append("学员：%s（班级：%s）" % (target, u.get("cls", "未分组")))
        lines.append("考核记录共 %d 条：" % len(recs))
        for i, x in enumerate(recs, 1):
            dims = x.get("dims") or {}
            lines.append("%d. %s：得分 %s / 100，用时 %s 秒%s" % (
                i,
                "实操模拟考核" if x.get("type") == "practical" else "正式考核",
                x.get("score", 0), x.get("elapsed", 0),
                ("，各维度得分 " + json.dumps(dims, ensure_ascii=False)) if dims else ""))
        pr = [a for a in recs if a.get("type") == "practical"]
        fr = [a for a in recs if a.get("type") == "formal"]
        lines.append("实操平均分：%s；正式考核平均分：%s；全部平均分：%s" % (_avg(pr), _avg(fr), _avg(recs)))
    elif rtype == "class":
        cls = None if target == "__all__" else target
        recs = [a for a in assessments if cls is None or a.get("cls") == cls]
        names = set(a.get("name") for a in recs if a.get("name"))
        pr = [a for a in recs if a.get("type") == "practical"]
        fr = [a for a in recs if a.get("type") == "formal"]
        lines.append("班级：%s" % (cls or "全部班级"))
        lines.append("学员人数：%d；考核记录：%d 条" % (len(names), len(recs)))
        lines.append("实操平均分：%s；正式考核平均分：%s；整体平均分：%s" % (_avg(pr), _avg(fr), _avg(recs)))
        dims = _dim_avg(recs)
        if dims:
            lines.append("各维度平均：" + "，".join("%s %s" % (k, v) for k, v in dims.items()))
    else:  # quality
        names = set(a.get("name") for a in assessments if a.get("name"))
        pr = [a for a in assessments if a.get("type") == "practical"]
        fr = [a for a in assessments if a.get("type") == "formal"]
        lines.append("平台整体数据：学员 %d 人，考核记录 %d 条" % (len(names), len(assessments)))
        lines.append("实操平均分：%s；正式考核平均分：%s；整体平均分：%s" % (_avg(pr), _avg(fr), _avg(assessments)))
        dims = _dim_avg(assessments)
        if dims:
            lines.append("各维度平均：" + "，".join("%s %s" % (k, v) for k, v in dims.items()))
    return "\n".join(lines)


def generate_report(state, rtype, target):
    """调用 DeepSeek 生成个性化报告，返回 (结果字典, 错误消息)。"""
    if rtype not in REPORT_LABELS:
        return None, "不支持的报告类型：%s" % rtype
    ctx = report_context(state, rtype, target)
    system = (
        "你是「三臂凿岩台车教学交互式智能体平台」的教务分析助手。请根据提供的平台考核数据，"
        "用中文撰写一份《%s》，结构清晰、客观专业，必须包含：总体评价、数据概览、优势与不足、"
        "改进建议四个部分。不要使用 Markdown 表格，控制在 600 字以内。" % REPORT_LABELS[rtype]
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "平台考核数据如下：\n" + ctx},
    ]
    result, err = forward_chat(messages, max_tokens=2048)
    if err:
        return None, err
    if not result.get("ok"):
        return None, result.get("error") or "报告生成失败"
    return {"ok": True, "report": result.get("reply", ""), "type": rtype, "target": target}, None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ---- CORS：允许任意来源（便于静态站点 / 本地开发调用本服务） ----
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # ---- 工具 ----
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # 安静模式
        pass

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            with LOCK:
                state = load_state()
            self._json({
                "ok": True,
                "service": "三臂凿岩台车 3D 教学交互服务",
                "uptime_s": round(time.time() - START_TIME, 1),
                "sessions": state.get("sessions", 0),
            })
            return
        if path == "/api/parts":
            self._json({"parts": PARTS})
            return
        if path == "/api/params":
            self._json(PARAMS)
            return
        if path == "/api/knowledge":
            self._json(KNOWLEDGE)
            return
        if path == "/api/interactions":
            with LOCK:
                state = load_state()
            top = sorted(state.get("clicks", {}).items(), key=lambda kv: -kv[1])[:12]
            self._json({
                "state": {
                    "sessions": state.get("sessions", 0),
                    "demo_plays": state.get("demo_plays", 0),
                    "explode_plays": state.get("explode_plays", 0),
                    "view_resets": state.get("view_resets", 0),
                    "total_time_ms": state.get("total_time_ms", 0),
                    "click_total": sum(state.get("clicks", {}).values()),
                },
                "top": [{"id": k, "count": v} for k, v in top],
                "events": state.get("events", [])[-200:],
            })
            return
        if path == "/api/users":
            with LOCK:
                state = load_state()
            self._json({"users": state.get("users", [])})
            return
        if path == "/api/assessments":
            with LOCK:
                state = load_state()
            self._json({"assessments": state.get("assessments", [])})
            return
        if path == "/api/teacher/summary":
            with LOCK:
                state = load_state()
            self._json(teacher_summary(state))
            return
        # 根路径：优先 index.html，否则重定向到教学页面
        if path == "/" or path == "/index.html":
            idx = os.path.join(ROOT, "index.html")
            page = os.path.join(ROOT, "三臂凿岩台车3D交互.html")
            if os.path.exists(idx):
                return super().do_GET()
            if os.path.exists(page):
                self.send_response(302)
                self.send_header("Location", "/" + os.path.basename(page))
                self.end_headers()
                return
        return super().do_GET()

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chat":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except Exception:
                body = {}
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                self._json({"ok": False, "error": "缺少 messages 参数"}, 400)
                return
            model = body.get("model") or DEEPSEEK_MODEL
            max_tokens = body.get("max_tokens") or DEEPSEEK_MAX_TOKENS
            try:
                max_tokens = int(max_tokens)
            except Exception:
                max_tokens = DEEPSEEK_MAX_TOKENS
            result, err = forward_chat(messages, model, max_tokens)
            if err:
                self._json({"ok": False, "error": err}, 503)
                return
            if not result.get("ok"):
                self._json(result, 502)
                return
            self._json(result)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            body = {}

        if path == "/api/users":
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "缺少 name 参数"}, 400)
                return
            cls = str(body.get("cls") or "").strip() or "未分组"
            with LOCK:
                state = load_state()
                users = state.setdefault("users", [])
                found = False
                for u in users:
                    if u.get("name") == name:
                        u["cls"] = cls
                        u["ts"] = int(time.time() * 1000)
                        found = True
                        break
                if not found:
                    users.append({"name": name, "cls": cls, "ts": int(time.time() * 1000)})
                save_state(state)
            self._json({"ok": True})
            return

        if path == "/api/assessments":
            atype = str(body.get("type") or "").strip()
            if atype not in ("practical", "formal", "online"):
                self._json({"ok": False, "error": "type 必须为 practical / formal / online"}, 400)
                return
            with LOCK:
                state = load_state()
                assessments = state.setdefault("assessments", [])
                assessments.append({
                    "name": str(body.get("name") or "").strip() or "未命名",
                    "cls": str(body.get("cls") or "").strip() or "未分组",
                    "role": str(body.get("role") or "student"),
                    "type": atype,
                    "score": max(0, min(100, int(body.get("score") or 0))),
                    "dims": body.get("dims") or {},
                    "correct": int(body.get("correct") or 0),
                    "totalQ": int(body.get("totalQ") or 0),
                    "elapsed": int(body.get("elapsed") or 0),
                    "ts": int(body.get("ts") or time.time() * 1000),
                })
                del assessments[:-2000]  # 仅保留最近 2000 条
                save_state(state)
            self._json({"ok": True})
            return

        if path == "/api/report":
            rtype = str(body.get("type") or "").strip()
            target = str(body.get("target") or "")
            if rtype not in REPORT_LABELS:
                self._json({"ok": False, "error": "type 必须为 personal / class / quality"}, 400)
                return
            if rtype == "personal" and not target:
                self._json({"ok": False, "error": "缺少 target（学员姓名）"}, 400)
                return
            if rtype == "class" and not target:
                target = "__all__"
            with LOCK:
                state = load_state()
            result, err = generate_report(state, rtype, target)
            if err:
                self._json({"ok": False, "error": err}, 503)
                return
            self._json(result)
            return

        if path != "/api/interactions":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        action = str(body.get("action") or "")
        part_id = str(body.get("partId") or "")
        ts = int(body.get("ts") or time.time() * 1000)
        with LOCK:
            state = load_state()
            if action == "session":
                state["sessions"] = state.get("sessions", 0) + 1
            elif action == "click" and part_id:
                clicks = state.setdefault("clicks", {})
                clicks[part_id] = clicks.get(part_id, 0) + 1
            elif action == "demo":
                state["demo_plays"] = state.get("demo_plays", 0) + 1
            elif action == "explode":
                state["explode_plays"] = state.get("explode_plays", 0) + 1
            elif action == "reset":
                state["view_resets"] = state.get("view_resets", 0) + 1
            elif action == "time":
                ms = int(body.get("ms") or 0)
                state["total_time_ms"] = state.get("total_time_ms", 0) + max(0, ms)
            events = state.setdefault("events", [])
            events.append({"action": action, "partId": part_id, "ts": ts})
            del events[:-400]  # 仅保留最近 400 条
            save_state(state)
        self._json({"ok": True})


def main():
    print("=" * 62)
    print("  三臂凿岩台车 3D 教学模型 · 本地前后端交互服务")
    print("=" * 62)
    print("  请在浏览器打开:  http://%s:%d" % (HOST, PORT))
    print("  按 Ctrl+C 停止服务。")
    print("=" * 62)
    try:
        HTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    main()
