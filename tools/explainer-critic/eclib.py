"""explainer-critic core: caption/script parsing, text metrics, pluggable judges, cut metrics, stats.

Used by build_bible.py (reference captions -> bible.json) and score.py (one script or cut -> report).

Judges (who answers the judgment questions: is this sentence a stake, a comparison, a turn, jargon; where do the
acts fall; how does it end):
  heuristic  regex and word lists, no API, free, deterministic. Coarse but consistent.
  jev        TypeSafe Jev (System One), TYPESAFE_API_KEY. Probabilities per sentence and per script.
  openai     any OpenAI-compatible chat endpoint: EXPLAINER_OPENAI_BASE, EXPLAINER_OPENAI_KEY, EXPLAINER_OPENAI_MODEL.
  fal        fal.ai OpenRouter router (FAL_KEY), EXPLAINER_FAL_MODEL (default google/gemini-3.5-flash-lite).
Act labels and the ending type come from `acts` (heuristic | openai | fal); Jev answers yes/no questions only, so with
--judge jev the acts default to heuristic unless you pass --acts.

A bible is only comparable with scores made by the same judge: build and score with the same --judge.
Model answers are cached by request hash in cache/ beside this file (or $AMR_CACHE_DIR), so re-runs are free.
Keys come from the environment or a .env file in the working directory ($AMR_ENV_FILE); they are never printed.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("AMR_CACHE_DIR") or (HERE / "cache")) / "explainer-critic"
ENV_FILE = Path(os.environ.get("AMR_ENV_FILE", ".env"))
JEV_PRICE_IN = 0.042  # USD per M input tokens (output free)
SPEND = {"usd": 0.0, "calls": 0, "cached": 0}
MAX_COST = [float(os.environ.get("EXPLAINER_MAX_COST", "1.0"))]
_lock = threading.Lock()
NOWIN = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def env_key(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"') or None
    return None


# ------------------------------------------------------------------ words with times
class Word:
    __slots__ = ("w", "t")

    def __init__(self, w, t):
        self.w, self.t = w, t


TAG = re.compile(r"\[(?:music|applause|laughter|__)\]|\[[a-z ,'-]+\]", re.I)  # caption tags + VO tags like [excited]


def _ts(s: str) -> float:
    p = [float(x) for x in s.strip().replace(",", ".").split(":")]
    while len(p) < 3:
        p.insert(0, 0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def clean(txt: str) -> str:
    txt = html.unescape(txt).replace(" ", " ")
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = TAG.sub(" ", txt)
    txt = re.sub(r"^\s*(>>|-)\s*", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def spread(text: str, t0: float, t1: float) -> list[Word]:
    """Spread a line's words over [t0, t1], longer words taking longer."""
    ws = text.split()
    if not ws:
        return []
    weights = [max(1, len(w)) for w in ws]
    tot, acc, out = sum(weights), 0, []
    for w, k in zip(ws, weights):
        out.append(Word(w, t0 + (t1 - t0) * acc / tot))
        acc += k
    return out


def parse_cues(text: str):
    """SRT or VTT -> [(start, end, raw_text)]."""
    cues = []
    for b in re.split(r"\n\n+", text.replace("\r", "")):
        lines = [l for l in b.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = re.match(r"\s*([\d:.,]+)\s*-->\s*([\d:.,]+)", l)
            if m:
                cues.append((_ts(m.group(1)), _ts(m.group(2)), "\n".join(lines[i + 1:])))
                break
    return cues


def words_from_captions(path: Path) -> list[Word]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    cues = parse_cues(raw)
    if "<c>" in raw:  # auto captions with word timings inside rolling cues
        words = []
        for s, _e, t in cues:
            for line in t.split("\n"):
                if "<c>" not in line:
                    continue
                first = re.match(r"^([^<]*)", line).group(1)
                parts = [(s, first)] + [(_ts(a), b) for a, b in re.findall(r"<([\d:.]+)><c>([^<]*)</c>", line)]
                for tt, w in parts:
                    for ww in clean(w).split():
                        words.append(Word(ww, tt))
        return words
    words = []
    for s, e, t in cues:
        words += spread(clean(t.replace("\n", " ")), s, e)
    return words


def _line_records(path: Path) -> list[dict]:
    """JSON / JSONL script -> [{"text", "speaker"?, "start"?, "end"?, "pause"?}]."""
    if path.suffix.lower() == ".jsonl":
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    d = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("lines") or d.get("script") or []
    out = []
    for r in d:
        out.append(r if isinstance(r, dict) else {"text": str(r)})
    return out


def words_from_records(recs: list[dict], wps: float) -> tuple[list[Word], str]:
    timed = all(r.get("start") is not None and r.get("end") is not None for r in recs if r.get("text"))
    words, t = [], 0.0
    for r in recs:
        txt = clean(str(r.get("text") or ""))
        if r.get("pause"):
            t += float(r["pause"])
        if not txt:
            continue
        if timed:
            words += spread(txt, float(r["start"]), float(r["end"]))
        else:
            dur = len(txt.split()) / wps
            words += spread(txt, t, t + dur)
            t += dur + 0.25  # breath between lines
    return words, ("line timings" if timed else f"estimated at {wps} words/s")


def words_from_csv(path: Path, wps: float) -> tuple[list[Word], str]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    recs = [{"text": r.get("text", ""), "start": r.get("start") or None, "end": r.get("end") or None,
             "speaker": r.get("speaker")} for r in rows]
    return words_from_records(recs, wps)


def load_words(path: Path, wps: float = 2.7) -> tuple[list[Word], str]:
    """-> (words, timing source). Captions carry real times; scripts are timed from the csv or estimated at wps."""
    suf = path.suffix.lower()
    if suf in (".vtt", ".srt"):
        return words_from_captions(path), "captions"
    if suf == ".csv":
        return words_from_csv(path, wps)
    if suf in (".json", ".jsonl"):
        return words_from_records(_line_records(path), wps)
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?m)^\s*#.*$", "", text)  # markdown headings are not narration
    text = re.sub(r"(?m)^\s*[A-Z][A-Za-z ]{0,20}:\s+", "", text)  # "NARRATOR: " speaker tags
    words, t = [], 0.0
    for para in re.split(r"\n\s*\n", text):
        p = clean(para.replace("\n", " "))
        if p:
            dur = len(p.split()) / wps
            words += spread(p, t, t + dur)
            t += dur + 0.25
    return words, f"estimated at {wps} words/s"


# ------------------------------------------------------------------ sentences
ABBR = re.compile(r"\b(Dr|Mr|Mrs|Ms|St|vs|etc|e\.g|i\.e|U\.S|approx)\.$", re.I)


def sentences(words: list[Word]) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        end = re.search(r"[.!?…]+[\"')\]]*$", w.w)
        nxt = words[i + 1].w if i + 1 < len(words) else ""
        if end and not ABBR.search(w.w) and (not nxt or nxt[0].isupper() or nxt[0].isdigit() or nxt[0] in "\"'("):
            out.append(cur)
            cur = []
        elif len(cur) >= 60:  # unpunctuated auto captions: force a break
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    res = []
    for k, ws in enumerate(out):
        nxt_t = out[k + 1][0].t if k + 1 < len(out) else ws[-1].t + 0.4 * max(1, len(ws[-1].w)) / 4
        res.append({"i": k, "text": " ".join(w.w for w in ws), "t0": round(ws[0].t, 2),
                    "t1": round(max(nxt_t, ws[-1].t), 2), "n": len(ws)})
    return res


# ------------------------------------------------------------------ regex features (used by every judge)
NUMWORDS = (r"two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
            r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
            r"hundreds|thousands?|millions?|billions?|trillions?|dozens?|half|twice|triple|double|percent|quarter")
NUM = re.compile(r"(\d|\b(" + NUMWORDS + r")\b|\bone in\b|\bone of every\b)", re.I)
YOU = re.compile(r"\b(you|your|yours|yourself|yourselves|you're|you've|you'll|you'd)\b", re.I)
WE = re.compile(r"\b(we|us|our|we're|let's)\b", re.I)
ANALOGY_RX = re.compile(r"\b(like a|like an|like the|like your|as if|imagine|think of|the size of|as big as|as small as|"
                        r"as long as a|as heavy as|about as|equivalent to|picture (this|a|an)|in other words|it's like|"
                        r"that's like|the same as|roughly the|bigger than a|smaller than a|heavier than a|times more|"
                        r"times the|enough to fill|lined up|stacked|end to end|a day's|kind of like|sort of like|"
                        r"just like|much like|similar to|resembles?|as \w+ as (a|an|the|your)|"
                        r"(is|are|was|were|acts?|works?|looks?|feels?|behaves?|sounds?) like)\b", re.I)
TURN_START = re.compile(r"^(but|however|yet|except|still|unfortunately|surprisingly|actually|and yet|"
                        r"here's the (thing|catch|problem|twist)|the (problem|catch|twist|trouble) is|turns out|"
                        r"it turns out|not quite|well,? not|not so fast|that's not)\b", re.I)
TURN_ANY = re.compile(r"\b(turns out|the catch|the problem is|the twist|which is wrong|is a myth|isn't true|"
                      r"we were wrong|backwards|the opposite)\b", re.I)
STAKES_RX = re.compile(r"\b(die|dies|dying|death|deadly|kill\w*|danger\w*|risk\w*|threat\w*|cost\w*|pay|paying|money|"
                       r"lose|losing|lost|harm\w*|hurt\w*|sick|disease|worst|nobody knows|no one knows|mystery|"
                       r"problem|disaster|catastroph\w*|extinct\w*|destroy\w*|poison\w*|toxic|afraid|fear|"
                       r"never|forever|end of|crisis|broke|ruin\w*|waste\w*|trapped|secret|hidden)\b", re.I)
GLOSS_RX = re.compile(r"\b(which means|that means|meaning|that is|basically|called|known as|in other words|"
                      r"a fancy word|a fancy name|short for|or simply|which is)\b|\(", re.I)
RESOLVE_RX = re.compile(r"^(so|in the end|which means|the answer|that's why|the good news|next time|the point|"
                        r"in other words|what this means|ultimately|maybe|perhaps|and that's|that is why|"
                        r"so next time|so the)\b", re.I)
TAKEAWAY_RX = re.compile(r"\b(next time|check|look for|look at|read the|try|flip|count|ask (for|about)|"
                         r"remember|keep an eye|watch for|you can)\b", re.I)
OPTIMISM_RX = re.compile(r"\b(hope\w*|bright|good news|better|luckily|fortunately|the future|we can|we will|"
                         r"progress|amazing|wonder\w*)\b", re.I)
CTA_RX = re.compile(r"\b(subscribe|comment below|in the comments|like this video|follow for|hit the bell)\b", re.I)
PROMO_RX = re.compile(r"\b(sponsor\w*|patreon|merch|our shop|our store|link in the description|link below|"
                      r"discount code|promo code|this video is brought)\b", re.I)
MORAL_RX = re.compile(r"\b(you should|you must|you need to|you have to|we should|we must|shame|stop being)\b", re.I)
COMMON_LONG = set("""everything everywhere something sometimes understand understanding information different
differently interesting important importantly especially incredible incredibly basically completely
temperature environment eventually absolutely experience experiences scientists everybody themselves
definitely immediately probably generally unfortunately surprisingly together otherwise government
international technology community communities restaurant restaurants vegetables ingredients ingredient
manufacturer manufacturers supermarket supermarkets breakfast chocolate strawberries strawberry
apparently especially extraordinary relationship relationships comfortable uncomfortable""".split())


def number_tokens(s: str) -> int:
    return len(NUM.findall(s))


# ------------------------------------------------------------------ HTTP + cache
def _post(url: str, body: dict, headers: dict, timeout: float = 120, tries: int = 5) -> dict:
    data = json.dumps(body).encode("utf-8")
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (401, 402, 403) or any(w in msg.lower() for w in ("locked", "balance", "top up", "exhausted")):
                raise SystemExit(f"STOP: HTTP {e.code} from {url.split('/')[2]}: key wrong or account locked / balance "
                                 f"empty. Not falling back to another judge; fix it and re-run.")
            last = f"HTTP {e.code}: {msg}"
            if e.code in (408, 429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"request failed after {tries} tries: {last}")


def _cache_path(kind: str, payload) -> Path:
    h = hashlib.sha256((kind + json.dumps(payload, sort_keys=True)).encode()).hexdigest()[:32]
    return CACHE / f"{kind}-{h}.json"


def cached(kind: str, payload, fn):
    p = _cache_path(kind, payload)
    if p.exists():
        with _lock:
            SPEND["cached"] += 1
        return json.loads(p.read_text(encoding="utf-8"))
    if SPEND["usd"] >= MAX_COST[0]:
        raise SystemExit(f"STOP: spend cap ${MAX_COST[0]:.2f} reached (--max-cost); nothing more sent")
    val, usd = fn()
    with _lock:
        SPEND["usd"] += usd
        SPEND["calls"] += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(val), encoding="utf-8")
    return val


def _json_from(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------ judge questions (shared wording)
SENT_Q = {
    "stakes": "tells the viewer why the topic matters: a danger, a cost, a surprising consequence, or an open mystery "
              "(a plain description of how something works is not stakes)",
    "analogy": "uses a metaphor, or compares something to an everyday object, scale or experience",
    "turn": "reverses, complicates or contradicts what the sentences just before it set up",
    "jargon": "uses a technical term an average 12-year-old would not know, without explaining it in the same sentence",
}
STRUCT_Q = {
    "open_specific": ("Do the first two sentences make one specific, surprising claim or show a concrete scene, "
                      "rather than a general introduction of the topic?", True),
    "central_question": ("Does the script set up one clear question early on that the rest of it answers?", True),
    "stakes_early": ("Within its first fifth, does the script tell the viewer why this matters to them personally?", True),
    "has_turn": ("Does the script at some point complicate or overturn the first explanation it gives "
                 "(a 'but' that changes the picture)?", True),
    "one_mechanism": ("Does the script explain how the thing works in plain, everyday words, at least once?", True),
    "numbers_made_real": ("When the script gives big or unusual numbers, does it usually compare them to something "
                          "the viewer can picture?", True),
    "ending_lands": ("Does the end leave the viewer with a takeaway or a new way of seeing the topic, rather than "
                     "just stopping or listing facts?", True),
    "fact_pileup": ("Is there a stretch of four or more facts in a row with no example, comparison, question or "
                    "story beat between them?", False),
    "unexplained_jargon": ("Does the script use technical terms that it never explains in plain words?", False),
    "lecture_tone": ("Does it read like a lecture or textbook rather than someone talking to a friend?", False),
    "moralising": ("Does it scold, moralise or tell the viewer what they should do with their life?", False),
}
SECTIONS = ["hook", "stakes", "mechanism", "complication", "twist", "resolution", "cta", "promo"]
ENDINGS = ["takeaway", "reframe", "optimistic", "question", "joke", "summary", "abrupt"]

ACTS_PROMPT = """You label the structure of an explainer video script. Title: {title}.
The script is given as numbered sentences. Split it into consecutive sections, each with ONE label from:
hook (the opening grab), stakes (why it matters to the viewer), mechanism (how it works / the explanation),
complication (a problem, limit or 'but' that changes the picture), twist (a surprising reversal or reveal),
resolution (the answer, takeaway or big-picture reframe), cta (asks the viewer to comment, subscribe, follow),
promo (sponsor, merch, membership, channel plug).
Labels may repeat. Use as few sections as describe it well (typically 4-12).
Also classify how the STORY ends (ignore trailing promo): one of
takeaway (a practical thing to do or check), reframe (a big-picture new way to see it), optimistic (hopeful note),
question (open question to the viewer), joke, summary (recaps facts), abrupt (just stops).
Also give the central question the video answers, paraphrased in under 12 words.
Reply with JSON only: {{"sections":[{{"label":"hook","start":0}},...],"ending":"reframe","central_question":"..."}}

{numbered}"""


# ------------------------------------------------------------------ judges
class Judge:
    name = "base"
    acts_name = "heuristic"

    def sentence_flags(self, sents: list[dict]) -> None:
        raise NotImplementedError

    def structural(self, sents: list[dict], res: dict) -> dict:
        raise NotImplementedError

    def acts(self, sents: list[dict], title: str) -> dict:
        return heuristic_acts(sents)


class HeuristicJudge(Judge):
    """No API. Probabilities are 0.1 / 0.5 / 0.8 style buckets from regexes and word lists."""
    name = "heuristic"

    def sentence_flags(self, sents):
        for s in sents:
            t = s["text"]
            strong = STAKES_RX.findall(t)
            stakes = 0.8 if strong else (0.65 if YOU.search(t) and ("?" in t or "why" in t.lower()) else 0.1)
            analogy = 0.8 if ANALOGY_RX.search(t) else 0.1
            turn = 0.8 if TURN_START.search(t) or TURN_ANY.search(t) else 0.1
            longw = [w for w in re.findall(r"[A-Za-z-]+", t) if len(w) >= 12 and w.lower() not in COMMON_LONG
                     and not w[0].isupper()]
            jargon = 0.8 if longw and not GLOSS_RX.search(t) else 0.1
            s["judge"] = {"stakes": stakes, "analogy": analogy, "turn": turn, "jargon": jargon}

    def structural(self, sents, res):
        n = len(sents)
        first2 = " ".join(s["text"] for s in sents[:2])
        fifth = sents[:max(1, n // 5)]
        quarter = sents[:max(1, n // 4)]
        J = lambda s, k: s.get("judge", {}).get(k, 0) >= 0.6  # noqa: E731
        num_s = [i for i, s in enumerate(sents) if number_tokens(s["text"])]
        made_real = [i for i in num_s if any(J(sents[j], "analogy") for j in range(max(0, i - 1), min(n, i + 2)))]
        p = {
            "open_specific": 0.8 if (number_tokens(first2) or J(sents[0], "stakes")) and "?" not in sents[0]["text"] else 0.3,
            "central_question": 0.8 if any(s["text"].rstrip("\"')").endswith("?") for s in quarter) else 0.3,
            "stakes_early": 0.8 if any(J(s, "stakes") for s in fifth) else 0.2,
            "has_turn": 0.85 if any(J(s, "turn") for s in sents) else 0.15,
            "one_mechanism": 0.8 if any(re.search(r"\b(because|so that|which means|that's why|works by|happens when|"
                                                  r"the reason)\b", s["text"], re.I) for s in sents) else 0.3,
            "numbers_made_real": round(len(made_real) / len(num_s), 2) if num_s else 0.5,
            "ending_lands": 0.85 if res.get("ending") in ("takeaway", "reframe", "optimistic", "question", "joke") else 0.2,
            "fact_pileup": 0.8 if res.get("longest_plain_run", 0) >= 5 else 0.2,
            "unexplained_jargon": 0.75 if sum(J(s, "jargon") for s in sents) >= 2 else 0.2,
            "lecture_tone": 0.75 if (res.get("you_per_100w", 0) + res.get("we_per_100w", 0) < 0.5
                                     and res.get("questions_per_min", 0) == 0) else 0.3,
            "moralising": 0.7 if any(MORAL_RX.search(s["text"]) for s in sents) else 0.1,
        }
        return p


class JevJudge(Judge):
    name = "jev"

    def __init__(self, acts="heuristic"):
        self.key = env_key("TYPESAFE_API_KEY")
        if not self.key:
            raise SystemExit("STOP: --judge jev needs TYPESAFE_API_KEY (environment or .env)")
        self.model = os.environ.get("EXPLAINER_JEV_MODEL", "jev-latest")
        self.base = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai")
        self.acts_impl = make_llm(acts) if acts in ("openai", "fal") else None
        self.acts_name = acts if self.acts_impl else "heuristic"

    def ask(self, state: dict, questions: dict[str, str]) -> dict[str, float]:
        def call():
            body = {"model": self.model, "state": state,
                    "questions": {k: {"type": "noul", "instructions": v} for k, v in questions.items()}}
            r = _post(self.base + "/v1/systemone", body, {"Authorization": f"Bearer {self.key}"}, timeout=180)
            ans = {k: round(float(a.get("noul", 0.0)) if isinstance(a, dict) else float(a), 3)
                   for k, a in (r.get("answers") or {}).items()}
            return ans, int((r.get("usage") or {}).get("input_tokens") or 0) * JEV_PRICE_IN / 1e6
        return cached("jev", {"m": self.model, "state": state, "q": questions}, call)

    def sentence_flags(self, sents, window=8):
        def job(start):
            chunk = sents[start:start + window]
            ctx = sents[max(0, start - 4):start]
            state = {"earlier_sentences": {f"e{c['i']}": c["text"] for c in ctx},
                     "sentences": {f"s{c['i']}": c["text"] for c in chunk}}
            qs = {f"{q}__{c['i']}": f"Does sentence `sentences.s{c['i']}` {tpl}?" for c in chunk for q, tpl in SENT_Q.items()}
            ans = self.ask(state, qs)
            for c in chunk:
                c["judge"] = {q: ans.get(f"{q}__{c['i']}", 0.0) for q in SENT_Q}
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(job, range(0, len(sents), window)))

    def structural(self, sents, res):
        script = " ".join(f"[{int(s['t0']) // 60}:{int(s['t0']) % 60:02d}] {s['text']}" for s in sents)[:60000]
        ans = self.ask({"script": script}, {k: "About the explainer script `script`: " + v[0] for k, v in STRUCT_Q.items()})
        return {k: ans.get(k, 0.0) for k in STRUCT_Q}

    def acts(self, sents, title):
        return self.acts_impl.acts(sents, title) if self.acts_impl else heuristic_acts(sents)


class ChatJudge(Judge):
    """Any chat model that returns JSON: OpenAI-compatible endpoints or fal's OpenRouter router."""

    def __init__(self, kind: str):
        self.name = self.acts_name = kind
        if kind == "openai":
            self.base = os.environ.get("EXPLAINER_OPENAI_BASE", "https://api.openai.com/v1").rstrip("/")
            self.key = env_key("EXPLAINER_OPENAI_KEY") or env_key("OPENAI_API_KEY")
            self.model = os.environ.get("EXPLAINER_OPENAI_MODEL", "gpt-4o-mini")
            if not self.key and "localhost" not in self.base and "127.0.0.1" not in self.base:
                raise SystemExit("STOP: --judge openai needs EXPLAINER_OPENAI_KEY (or a local EXPLAINER_OPENAI_BASE)")
        else:
            self.key = env_key("FAL_KEY")
            self.model = os.environ.get("EXPLAINER_FAL_MODEL", "google/gemini-3.5-flash-lite")
            if not self.key:
                raise SystemExit("STOP: --judge fal needs FAL_KEY (environment or .env)")

    def chat(self, prompt: str) -> str:
        def call():
            if self.name == "openai":
                r = _post(self.base + "/chat/completions",
                          {"model": self.model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
                          {"Authorization": f"Bearer {self.key}"} if self.key else {}, timeout=240)
                return {"out": r["choices"][0]["message"]["content"]}, 0.0  # price unknown: counted as calls
            body = {"model": self.model, "prompt": prompt, "temperature": 0}
            try:
                r = _post("https://fal.run/openrouter/router", body, {"Authorization": f"Key {self.key}"}, timeout=240)
            except RuntimeError as e:
                if "easoning is mandatory" not in str(e):
                    raise
                body["reasoning"] = True
                r = _post("https://fal.run/openrouter/router", body, {"Authorization": f"Key {self.key}"}, timeout=240)
            return {"out": r.get("output", "")}, float((r.get("usage") or {}).get("cost") or 0.0)
        return cached(self.name, {"m": self.model, "p": prompt}, call)["out"]

    def sentence_flags(self, sents, window=12):
        crit = "\n".join(f"- {k}: the sentence {v}" for k, v in SENT_Q.items())

        def job(start):
            chunk = sents[start:start + window]
            ctx = sents[max(0, start - 3):start]
            prompt = ("For each numbered sentence of an explainer script, give the probability (0-1) of each flag.\n"
                      f"{crit}\nContext (earlier sentences, do not rate):\n"
                      + "\n".join(f"  {c['text']}" for c in ctx)
                      + "\nRate these:\n" + "\n".join(f"{c['i']}: {c['text']}" for c in chunk)
                      + '\nReply with JSON only: {"<number>": {"stakes": p, "analogy": p, "turn": p, "jargon": p}, ...}')
            d = _json_from(self.chat(prompt)) or {}
            for c in chunk:
                r = d.get(str(c["i"])) or {}
                c["judge"] = {q: float(r.get(q, 0.0) or 0.0) for q in SENT_Q}
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(job, range(0, len(sents), window)))

    def structural(self, sents, res):
        script = "\n".join(f"[{int(s['t0']) // 60}:{int(s['t0']) % 60:02d}] {s['text']}" for s in sents)[:60000]
        qs = "\n".join(f"- {k}: {v[0]}" for k, v in STRUCT_Q.items())
        d = _json_from(self.chat(f"Read this explainer script and answer each question with a probability (0-1) "
                                 f"that the answer is yes.\n{qs}\nReply with JSON only: {{\"<id>\": p, ...}}\n\n{script}")) or {}
        return {k: float(d.get(k, 0.5) or 0.0) for k in STRUCT_Q}

    def acts(self, sents, title):
        numbered = "\n".join(f"{s['i']}: {s['text']}" for s in sents)
        d = _json_from(self.chat(ACTS_PROMPT.format(title=title or "(unknown)", numbered=numbered)))
        if not d:
            return heuristic_acts(sents)
        secs = sorted([s for s in d.get("sections", []) if s.get("label") in SECTIONS and isinstance(s.get("start"), int)],
                      key=lambda s: s["start"])
        if not secs or secs[0]["start"] != 0:
            secs.insert(0, {"label": "hook", "start": 0})
        return {"sections": secs, "ending": d.get("ending") if d.get("ending") in ENDINGS else "unknown",
                "central_question": str(d.get("central_question", ""))[:120]}


def make_llm(kind: str) -> ChatJudge:
    return ChatJudge(kind)


def make_judge(kind: str, acts: str | None = None) -> Judge:
    if kind == "heuristic":
        return HeuristicJudge()
    if kind == "jev":
        return JevJudge(acts or "heuristic")
    if kind in ("openai", "fal"):
        return ChatJudge(kind)
    raise SystemExit(f"unknown judge {kind}")


def heuristic_acts(sents: list[dict]) -> dict:
    """Section labels and ending type without a model."""
    n = len(sents)
    J = lambda s, k: s.get("judge", {}).get(k, 0) >= 0.6  # noqa: E731
    promo_i = n
    for i in range(n - 1, max(-1, n - 8), -1):
        if PROMO_RX.search(sents[i]["text"]):
            promo_i = i
    story = sents[:promo_i] or sents
    m = len(story)
    secs = [{"label": "hook", "start": 0}]
    st = next((s["i"] for s in story[1:max(2, m // 4)] if J(s, "stakes")), None)
    if st:
        secs.append({"label": "stakes", "start": st})
    after = max(st or 0, 1) + 1
    if after < m:
        secs.append({"label": "mechanism", "start": after})
    turns = [s["i"] for s in story if J(s, "turn") and s["i"] >= max(2, int(0.12 * m))]  # not the hook's own "but"
    res_i = next((s["i"] for s in story if s["i"] >= int(0.75 * m) and RESOLVE_RX.search(s["text"])), None)
    if res_i is None:
        res_i = max(2, int(0.86 * m))
    if turns and turns[0] < res_i:
        secs.append({"label": "complication", "start": turns[0]})
        if turns[0] + 1 < res_i:
            secs.append({"label": "mechanism", "start": turns[0] + 1})
        tw = next((t for t in turns if t >= 0.5 * m and t >= turns[0] + max(2, 0.15 * m) and t < res_i), None)
        if tw:
            secs.append({"label": "twist", "start": tw})
    if res_i < m:
        secs.append({"label": "resolution", "start": res_i})
    if promo_i < n:
        secs.append({"label": "promo", "start": promo_i})
    if any(CTA_RX.search(s["text"]) for s in story[-3:]):
        secs.append({"label": "cta", "start": next(s["i"] for s in story[-3:] if CTA_RX.search(s["text"]))})
    secs = sorted({s["start"]: s for s in secs}.values(), key=lambda s: s["start"])
    last = " ".join(s["text"] for s in story[-2:])
    tail = story[-1]["text"]
    if tail.rstrip("\"')").endswith("?"):
        ending = "question"
    elif TAKEAWAY_RX.search(last):
        ending = "takeaway"
    elif re.match(r"^(to recap|in summary|so,? to sum)", tail, re.I) or (number_tokens(last) >= 2 and not YOU.search(last)):
        ending = "summary"
    elif OPTIMISM_RX.search(last):
        ending = "optimistic"
    elif story[-1]["n"] <= 3 and not YOU.search(last):
        ending = "abrupt"
    else:
        ending = "reframe"
    q = next((s["text"] for s in story[:max(1, m // 4)] if s["text"].rstrip("\"')").endswith("?")), "")
    return {"sections": secs, "ending": ending, "central_question": q[:120]}


# ------------------------------------------------------------------ cut metrics (local, free)
def _probe_duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, **NOWIN).stdout.strip()
    return float(out or 0)


def scene_cuts(video: Path, threshold: float = 0.30) -> list[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                        f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **NOWIN)
    out = []
    for c in (float(m) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)):
        if not out or c - out[-1] > 0.25:  # dissolves fire several frames
            out.append(c)
    return out


def static_stretches(video: Path, min_dur: float = 1.5, noise: str = "-50dB") -> list[tuple[float, float]]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                        f"scale=320:-2,freezedetect=n={noise}:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **NOWIN)
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", p.stderr)]
    dur = _probe_duration(video)
    ends += [dur] * (len(starts) - len(ends))  # a freeze that lasts to the end has no freeze_end
    return [(s, e) for s, e in zip(starts, ends)]


def picture_changes(video: Path, fps: float = 4.0, frac: float = 0.12, pix: float = 0.08) -> list[float]:
    """A 'picture change' = at least `frac` of a small grey frame differs by more than `pix` from the frame at the last
    change: cuts, pans, zooms, a new element, a big move. A small subtitle pop alone does not count. Times in s."""
    import numpy as np
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(video)], capture_output=True, text=True, **NOWIN).stdout.strip().split(",")
    w, h = int(pr[0]), int(pr[1])
    W, H = (96, 54) if w >= h else (54, 96)
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf",
                        f"fps={fps},scale={W}:{H}:flags=area,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, **NOWIN)
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (W * H)
    if not n:
        return []
    frames = buf[: n * W * H].reshape(n, H, W).astype(np.float32) / 255.0
    out, anchor = [], frames[0]
    for i in range(1, n):
        if float((np.abs(frames[i] - anchor) > pix).mean()) > frac:
            out.append(round(i / fps, 2))
            anchor = frames[i]
    return out


def cut_metrics(video: Path) -> dict:
    dur = _probe_duration(video)
    pcs = picture_changes(video)
    cuts = scene_cuts(video)
    bounds = [0.0] + cuts + [dur]
    shots = [round(b - a, 2) for a, b in zip(bounds, bounds[1:]) if b - a > 0.04]
    frz = static_stretches(video)
    pb = [0.0] + pcs + [dur]
    gaps = [b - a for a, b in zip(pb, pb[1:])]
    gi = max(range(len(gaps)), key=lambda i: gaps[i]) if gaps else 0
    return {"duration": round(dur, 2),
            "picture_changes_per_min": round(len(pcs) / dur * 60, 1) if dur else None,
            "picture_gap_median": round(statistics.median(gaps), 2) if gaps else None,
            "picture_gap_p90": pct(gaps, 90),
            "longest_no_change": round(max(gaps, default=0), 2), "longest_no_change_at": round(pb[gi], 2) if gaps else 0,
            "picture_gaps": [round(g, 2) for g in gaps],
            "cuts": [round(c, 2) for c in cuts], "shots": shots,
            "shot_median": round(statistics.median(shots), 2) if shots else None,
            "shot_p75": pct(shots, 75), "shot_p90": pct(shots, 90),
            "cuts_per_min": round(len(cuts) / dur * 60, 1) if dur else None,
            "longest_shot": max(shots, default=0),
            "static_stretches": [(round(s, 2), round(e, 2)) for s, e in frz],
            "longest_static": round(max([e - s for s, e in frz], default=0.0), 2),
            "static_share": round(sum(e - s for s, e in frz) / dur, 3) if dur else 0}


# ------------------------------------------------------------------ stats
def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 3)


def dist(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"n": len(xs), "p10": pct(xs, 10), "p25": pct(xs, 25), "p50": pct(xs, 50), "p75": pct(xs, 75),
            "p90": pct(xs, 90)}


def rhythm(story: list[dict], runtime: float) -> dict:
    """Punch lines (a <=6-word sentence right after a >=15-word one) per minute, share of <=5-word sentences, and the
    longest run of 'plain' sentences (no comparison, no turn, no question): a fact pile-up."""
    n = [s["n"] for s in story]
    punch = sum(1 for a, b in zip(n, n[1:]) if a >= 15 and b <= 6)
    run = best = 0
    best_at = start = 0.0
    for s in story:
        j = s.get("judge", {})
        if j.get("analogy", 0) >= 0.6 or j.get("turn", 0) >= 0.6 or s["text"].rstrip("\"')").endswith("?"):
            run = 0
        else:
            if run == 0:
                start = s["t0"]
            run += 1
            if run > best:
                best, best_at = run, start
    return {"punch_per_min": round(punch / max(runtime / 60, 0.1), 2),
            "short_sentence_share": round(sum(1 for x in n if x <= 5) / max(1, len(n)), 3),
            "longest_plain_run": best, "longest_plain_run_at": best_at}


# ------------------------------------------------------------------ the full text analysis
def analyse(words: list[Word], judge: Judge, title: str = "") -> dict:
    sents = sentences(words)
    if not sents:
        raise ValueError("no words")
    judge.sentence_flags(sents)
    acts = judge.acts(sents, title)
    secs = acts["sections"]
    story_end_i = len(sents)
    for s in reversed(secs):  # story = everything before a trailing promo
        if s["label"] == "promo":
            story_end_i = s["start"]
        else:
            break
    story = sents[:max(1, story_end_i)]
    T = max(story[-1]["t1"], 1.0)
    nwords = sum(s["n"] for s in story)
    buckets = [0] * 10
    for w in words:
        if w.t < T:
            buckets[min(9, int(w.t / T * 10))] += 1
    bucket_wps = [round(b / (T / 10), 2) for b in buckets]
    med_b = statistics.median(bucket_wps[1:9]) if any(bucket_wps) else 0
    sag = min(bucket_wps[1:9]) / med_b if med_b else None  # first/last tenth are ramp in/out
    J = lambda s, k, th=0.6: s.get("judge", {}).get(k, 0) >= th  # noqa: E731
    first_num = next((s for s in story if number_tokens(s["text"])), None)
    first_stakes = next((s for s in story if J(s, "stakes")), None)
    hook_s = min([x["t1"] for x in (first_num, first_stakes) if x] or [T])
    turn_sents = [s for s in story if J(s, "turn") or (TURN_START.search(s["text"]) and J(s, "turn", 0.4))]
    turn_pos = [round(sents[s["start"]]["t0"] / T, 3) for s in secs
                if s["label"] in ("complication", "twist") and s["start"] < len(story)]
    qs = [s for s in story if s["text"].rstrip("\"')").endswith("?")]
    lens = [s["n"] for s in story]
    mins = T / 60
    sec_out = []
    for k, s in enumerate(secs):
        if s["start"] >= len(sents):
            continue
        end_i = secs[k + 1]["start"] if k + 1 < len(secs) else len(sents)
        sec_out.append({"label": s["label"], "start_s": sents[s["start"]]["t0"],
                        "start_pct": round(sents[s["start"]]["t0"] / T, 3), "sentences": [s["start"], end_i - 1]})
    labels_story = [s["label"] for s in sec_out if s["start_pct"] < 1.0]
    first = lambda lab: next((s["start_pct"] for s in sec_out if s["label"] == lab), None)  # noqa: E731
    res = {
        "title": title, "judge": judge.name, "acts_judge": judge.acts_name,
        "runtime_s": round(T, 2), "words": nwords, "sentences_n": len(story),
        "wps": round(nwords / max(1.0, T - story[0]["t0"]), 2),
        "pacing_curve_wps": bucket_wps,
        "pacing_sag": round(sag, 2) if sag is not None else None,
        "pacing_cv": round(statistics.pstdev(bucket_wps[1:9]) / med_b, 2) if med_b else None,
        "first_number_s": first_num["t1"] if first_num else None,
        "first_stakes_s": first_stakes["t1"] if first_stakes else None,
        "hook_s": round(hook_s, 2), "hook_pct": round(hook_s / T, 3),
        "turns_per_min": round(len(turn_sents) / mins, 2),
        "turn_positions_pct": turn_pos,
        "first_turn_pct": turn_pos[0] if turn_pos else None,
        "questions_per_min": round(len(qs) / mins, 2),
        "you_per_100w": round(sum(len(YOU.findall(s["text"])) for s in story) / max(1, nwords) * 100, 2),
        "we_per_100w": round(sum(len(WE.findall(s["text"])) for s in story) / max(1, nwords) * 100, 2),
        "analogies_per_min": round(sum(1 for s in story if J(s, "analogy")) / mins, 2),
        "numbers_per_min": round(sum(number_tokens(s["text"]) for s in story) / mins, 2),
        "jargon_per_min": round(sum(1 for s in story if J(s, "jargon", 0.7)) / mins, 2),
        "sent_len_median": statistics.median(lens), "sent_len_p90": pct(lens, 90),
        "long_sentence_share": round(sum(1 for x in lens if x > 25) / len(lens), 3),
        **rhythm(story, T),
        "sections": sec_out, "section_sequence": labels_story,
        "n_mechanism_blocks": labels_story.count("mechanism"),
        "complication_first_pct": first("complication"), "twist_first_pct": first("twist"),
        "resolution_first_pct": first("resolution"),
        "has_cta": "cta" in labels_story, "has_promo": "promo" in [s["label"] for s in sec_out],
        "ending": acts.get("ending"), "central_question": acts.get("central_question", ""),
    }
    res["turn_count_story"] = len(turn_pos)
    res["structural"] = judge.structural(story, res)
    res["_sentences"] = sents
    return res


# ------------------------------------------------------------------ copy guard
def norm_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def reference_texts(dirs: list[Path], exclude_stem: str = "") -> list[str]:
    """All caption / transcript text under the given folders (recursive): .vtt .srt .txt."""
    out = []
    for d in dirs:
        if not d or not Path(d).exists():
            continue
        files = [Path(d)] if Path(d).is_file() else [p for p in Path(d).rglob("*") if p.suffix.lower() in (".vtt", ".srt", ".txt")]
        for f in files:
            if exclude_stem and f.name.split(".")[0] == exclude_stem:
                continue
            try:
                if f.suffix.lower() in (".vtt", ".srt"):
                    out.append(" ".join(w.w for w in words_from_captions(f)))
                else:
                    out.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    return out


def copy_check(sents: list[dict], ref_texts: list[str], n: int = 8) -> list[dict]:
    """Every sentence sharing a run of >= n words with any reference text."""
    grams = set()
    for t in ref_texts:
        toks = norm_tokens(t)
        grams.update(" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1))
    hits = []
    if not grams:
        return hits
    for s in sents:
        toks = norm_tokens(s["text"])
        for i in range(len(toks) - n + 1):
            g = " ".join(toks[i:i + n])
            if g in grams:
                hits.append({"t": s["t0"], "phrase": g, "sentence": s["text"]})
                break
    return hits
