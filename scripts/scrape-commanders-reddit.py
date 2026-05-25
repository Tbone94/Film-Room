#!/usr/bin/env python3
"""
Commanders Pulse data builder

No pip dependencies. No Reddit login. Designed for GitHub Actions.

Source strategy, in order:
1) PullPush public Reddit submission search API. This is more reliable from
   GitHub Actions than direct reddit.com scraping in many cases.
2) old.reddit.com RSS feeds.
3) reddit.com RSS feeds.
4) reddit JSON endpoints.
5) lightweight reddit HTML title extraction as a final fallback.

If no posts are collected, the script still writes data/reddit-pulse.json with
clear source_status/debug info so the Action log shows exactly what happened.
"""
from __future__ import annotations

import email.utils
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

OUTPUT_PATH = "data/reddit-pulse.json"
HISTORY_PATH = "data/reddit-pulse-history.json"
TEAM_ID_ESPN = 28
STALE_AFTER_HOURS = 72
REQUEST_TIMEOUT = 18
REQUEST_DELAY = 0.75

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 CommandersPulse/1.4"
)

SUBS_TO_SCAN = [
    {
        "key": "commanders",
        "subreddit": "Commanders",
        "categories": ["hot", "new", "top"],
        "queries": [
            "Commanders", "Jayden Daniels", "Washington Commanders",
            "Commanders offense", "Commanders defense", "Commanders draft",
            "Commanders trade", "Commanders injury", "Commanders stadium",
        ],
    },
    {
        "key": "nfl_commanders",
        "subreddit": "nfl",
        "categories": [],
        "queries": ["Commanders", "Washington Commanders", "Jayden Daniels"],
    },
    {
        "key": "fantasy_commanders",
        "subreddit": "fantasyfootball",
        "categories": [],
        "queries": ["Jayden Daniels fantasy", "Commanders fantasy", "McLaurin fantasy"],
    },
]

FALLBACK_PLAYERS = {
    "daniels": "Jayden Daniels",
    "jd5": "Jayden Daniels",
    "mclaurin": "Terry McLaurin",
    "ertz": "Zach Ertz",
    "ekeler": "Austin Ekeler",
    "robinson": "Brian Robinson Jr.",
    "wagner": "Bobby Wagner",
    "lattimore": "Marshon Lattimore",
    "payne": "Daron Payne",
    "allen": "Jonathan Allen",
    "cosmi": "Sam Cosmi",
    "quinn": "Dan Quinn",
    "peters": "Adam Peters",
}

TOPIC_KEYWORDS = {
    "Jayden Daniels": ["daniels", "jayden", "jd5", "jd", "qb1"],
    "Offense": ["offense", "offensive", "oc", "play calling", "scoring", "red zone", "passing", "rushing"],
    "Defense": ["defense", "defensive", "dc", "pass rush", "secondary", "sack", "turnover", "coverage"],
    "Draft & Roster": ["draft", "pick", "rookie", "trade", "free agent", "signing", "roster", "cut", "waiver"],
    "Coaching": ["quinn", "coach", "coaching", "staff", "scheme", "play call", "game plan", "peters"],
    "O-Line": ["line", "o-line", "offensive line", "blocking", "protection", "tackle", "guard", "center"],
    "Injuries": ["injury", "injured", "hurt", "ir", "out", "questionable", "doubtful", "hamstring", "knee", "ankle"],
    "Stadium & Culture": ["stadium", "fans", "attendance", "culture", "uniforms", "rebrand", "ownership", "tailgate"],
    "NFC East": ["cowboys", "eagles", "giants", "nfc east", "division", "rivalry", "dallas", "philly"],
    "Season Outlook": ["season", "record", "wins", "playoff", "super bowl", "prediction", "expectations", "over under"],
    "Fantasy Football": ["fantasy", "adp", "draft capital", "sleeper", "waiver", "start sit", "league winner"],
}

STRONG_POSITIVE = [
    "elite", "beast", "monster", "stud", "generational", "franchise", "pro bowl", "all pro",
    "dominant", "unstoppable", "clutch", "goat", "mvp", "breakout", "lethal", "electric",
    "special", "game changer", "locked in", "baller", "built different", "league winner",
    "super bowl", "playoff", "contender", "love it", "all timer",
]
POSITIVE = [
    "good", "great", "solid", "improving", "better", "growth", "excited", "healthy", "confident",
    "impressed", "athletic", "fast", "strong", "win", "winning", "hope", "optimistic", "love",
    "hype", "hyped", "chemistry", "development", "potential", "underrated", "upgrade", "improved",
    "depth", "talent", "promising", "bright future", "looks sharp", "steal", "value", "ceiling",
]
NEGATIVE = [
    "bad", "concern", "worried", "disappointing", "slow", "injury", "risky", "overrated",
    "overpay", "limited", "decline", "regression", "aging", "old", "washed", "backup", "benched",
    "frustrating", "inconsistent", "weak", "liability", "problem", "issue", "miss", "lose", "losing",
    "struggling", "questionable", "doubt", "cooked",
]
STRONG_NEGATIVE = [
    "bust", "trash", "terrible", "awful", "disaster", "fraud", "done", "finished", "washed up",
    "waste", "nightmare", "toxic", "cut him", "release him", "tank", "tanking", "dumpster fire",
    "trainwreck", "embarrassing", "pathetic", "worst", "horrible", "garbage",
]


def clean_text(value: Any, max_len: int = 260) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def request_text(url: str, accept: str = "*/*") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def source_attempt(source_status: Dict[str, Any], label: str, ok: bool, count: int = 0, error: str = "") -> None:
    source_status.setdefault("attempts", []).append({
        "source": label,
        "ok": bool(ok),
        "count": int(count or 0),
        "error": error[:220],
    })


def normalize_post(post: Dict[str, Any], default_subreddit: str = "", source_type: str = "unknown") -> Optional[Dict[str, Any]]:
    title = clean_text(post.get("title"), 220)
    if not title:
        return None

    permalink = post.get("permalink") or post.get("full_link") or ""
    url = post.get("url") or post.get("link") or ""
    if permalink and not str(permalink).startswith("http"):
        permalink = "https://reddit.com" + str(permalink)
    if not permalink and post.get("id") and default_subreddit:
        permalink = f"https://reddit.com/r/{default_subreddit}/comments/{post.get('id')}/"

    return {
        "title": title,
        "selftext": clean_text(post.get("selftext") or post.get("body") or post.get("summary"), 280),
        "score": safe_int(post.get("score")),
        "comments": safe_int(post.get("num_comments") or post.get("comments") or post.get("comment_count")),
        "created": safe_float(post.get("created_utc") or post.get("created") or post.get("created_at")),
        "url": permalink or url,
        "subreddit": clean_text(post.get("subreddit") or default_subreddit, 60),
        "flair": clean_text(post.get("link_flair_text") or post.get("flair"), 80),
        "source_type": source_type,
    }


def deduplicate(posts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for post in posts:
        key = re.sub(r"[^a-z0-9]", "", post.get("title", "").lower())[:110]
        if key and key not in seen:
            seen.add(key)
            unique.append(post)
    return unique


def fetch_pullpush(subreddit: str, query: str = "", limit: int = 50) -> Tuple[List[Dict[str, Any]], str, str]:
    params = {
        "subreddit": subreddit,
        "size": str(min(limit, 100)),
        "sort": "desc",
        "sort_type": "created_utc",
        "after": "45d",
    }
    if query:
        params["q"] = query
    url = "https://api.pullpush.io/reddit/search/submission/?" + urllib.parse.urlencode(params)
    text = request_text(url, accept="application/json,text/plain,*/*")
    data = json.loads(text)
    raw_posts = data.get("data") if isinstance(data, dict) else []
    if not isinstance(raw_posts, list):
        raw_posts = []
    posts = []
    for raw in raw_posts:
        if isinstance(raw, dict):
            normalized = normalize_post(raw, subreddit, "pullpush")
            if normalized:
                normalized["source_category"] = f"pullpush:{query or 'recent'}"
                posts.append(normalized)
    meta = data.get("metadata", {}) if isinstance(data, dict) else {}
    return posts[:limit], url, f"metadata={clean_text(meta, 180)}"


def rss_time_to_epoch(value: str) -> float:
    if not value:
        return 0.0
    try:
        return email.utils.parsedate_to_datetime(value).timestamp()
    except Exception:
        try:
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0


def parse_reddit_rss(xml_text: str, subreddit: str, source_category: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns) or root.findall(".//{http://www.w3.org/2005/Atom}entry") or root.findall(".//entry")
    posts = []
    for entry in entries:
        def find_text(paths: List[str]) -> str:
            for path in paths:
                node = entry.find(path, ns) if path.startswith("atom:") else entry.find(path)
                if node is not None and node.text:
                    return node.text
            return ""
        title = clean_text(find_text(["atom:title", "title"]), 220)
        summary = clean_text(find_text(["atom:content", "atom:summary", "summary", "description"]), 280)
        link = ""
        for link_node in entry.findall("atom:link", ns) + entry.findall("link"):
            href = link_node.attrib.get("href")
            rel = link_node.attrib.get("rel", "alternate")
            if href and rel in ("alternate", ""):
                link = href
                break
        if not link:
            link = find_text(["atom:id", "id"])
        post = normalize_post({
            "title": title,
            "selftext": summary,
            "created_utc": rss_time_to_epoch(find_text(["atom:updated", "atom:published", "updated", "pubDate"])),
            "url": link,
            "subreddit": subreddit,
        }, subreddit, "rss")
        if post:
            post["source_category"] = source_category
            posts.append(post)
    return posts


def fetch_rss(url: str, subreddit: str, source_category: str, limit: int) -> List[Dict[str, Any]]:
    text = request_text(url, accept="application/atom+xml,application/rss+xml,text/xml,text/plain,*/*")
    return parse_reddit_rss(text, subreddit, source_category)[:limit]


def fetch_reddit_json(url: str, subreddit: str, source_category: str, limit: int) -> List[Dict[str, Any]]:
    text = request_text(url, accept="application/json,text/plain,*/*")
    data = json.loads(text)
    children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
    posts = []
    for child in children:
        raw = child.get("data") if isinstance(child, dict) else None
        if isinstance(raw, dict):
            post = normalize_post(raw, subreddit, "reddit_json")
            if post:
                post["source_category"] = source_category
                posts.append(post)
    return posts[:limit]


def parse_reddit_html(text: str, subreddit: str, source_category: str, limit: int) -> List[Dict[str, Any]]:
    posts = []
    # Modern reddit often renders shreddit-post tags with post-title attributes.
    for match in re.finditer(r"<shreddit-post\b([^>]+)>", text, flags=re.I):
        attrs = match.group(1)
        def attr(name: str) -> str:
            m = re.search(rf'{name}="([^"]*)"', attrs, flags=re.I)
            return html.unescape(m.group(1)) if m else ""
        title = attr("post-title") or attr("title")
        permalink = attr("permalink") or attr("content-href")
        score = attr("score")
        comments = attr("comment-count")
        post = normalize_post({
            "title": title,
            "permalink": permalink,
            "score": score,
            "num_comments": comments,
            "subreddit": subreddit,
        }, subreddit, "reddit_html")
        if post:
            post["source_category"] = source_category
            posts.append(post)
        if len(posts) >= limit:
            break
    # Old reddit fallback.
    if not posts:
        for match in re.finditer(r'<a[^>]+class="[^"]*title[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, flags=re.I | re.S):
            href, title_html = match.groups()
            title = clean_text(title_html, 220)
            post = normalize_post({"title": title, "permalink": href, "subreddit": subreddit}, subreddit, "reddit_html_old")
            if post:
                post["source_category"] = source_category
                posts.append(post)
            if len(posts) >= limit:
                break
    return posts[:limit]


def fetch_html(url: str, subreddit: str, source_category: str, limit: int) -> List[Dict[str, Any]]:
    text = request_text(url, accept="text/html,*/*")
    return parse_reddit_html(text, subreddit, source_category, limit)


def try_source(label: str, source_status: Dict[str, Any], fn) -> List[Dict[str, Any]]:
    try:
        posts = fn()
        source_attempt(source_status, label, bool(posts), len(posts), "" if posts else "0 posts returned")
        print(f"      {label}: {len(posts)} posts")
        return posts
    except urllib.error.HTTPError as exc:
        msg = f"HTTP {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        msg = f"URL error: {exc.reason}"
    except Exception as exc:
        msg = f"{type(exc).__name__}: {str(exc)}"
    source_attempt(source_status, label, False, 0, msg)
    print(f"      {label}: FAILED — {msg[:130]}")
    return []


def collect_for_config(config: Dict[str, Any], source_status: Dict[str, Any]) -> List[Dict[str, Any]]:
    subreddit = config["subreddit"]
    posts: List[Dict[str, Any]] = []

    print(f"\nScanning r/{subreddit}...")

    # Primary: PullPush recent subreddit posts.
    if config.get("categories"):
        posts.extend(try_source(
            f"pullpush:r/{subreddit}:recent",
            source_status,
            lambda: fetch_pullpush(subreddit, "", 80)[0],
        ))
        time.sleep(REQUEST_DELAY)

    # PullPush targeted searches.
    for query in config.get("queries", []):
        posts.extend(try_source(
            f"pullpush:r/{subreddit}:search:{query}",
            source_status,
            lambda query=query: fetch_pullpush(subreddit, query, 25)[0],
        ))
        time.sleep(REQUEST_DELAY)

    # Reddit RSS category fallbacks. old.reddit first.
    for category in config.get("categories", []):
        paths = {
            "hot": [".rss", "hot/.rss"],
            "new": ["new/.rss"],
            "top": ["top/.rss?t=week"],
        }.get(category, [f"{category}/.rss"])
        for host in ("old.reddit.com", "www.reddit.com"):
            for path in paths:
                url = f"https://{host}/r/{subreddit}/{path}"
                posts.extend(try_source(
                    f"rss:{host}:r/{subreddit}:{category}",
                    source_status,
                    lambda url=url, category=category: fetch_rss(url, subreddit, category, 35),
                ))
                if posts:
                    break
            if posts:
                break
        time.sleep(REQUEST_DELAY)

    # Reddit RSS search fallbacks.
    for query in config.get("queries", [])[:4]:
        encoded = urllib.parse.quote_plus(query)
        for host in ("old.reddit.com", "www.reddit.com"):
            url = f"https://{host}/r/{subreddit}/search.rss?q={encoded}&restrict_sr=on&sort=new&t=month"
            result = try_source(
                f"rss-search:{host}:r/{subreddit}:{query}",
                source_status,
                lambda url=url, query=query: fetch_rss(url, subreddit, f"search:{query}", 20),
            )
            posts.extend(result)
            if result:
                break
        time.sleep(REQUEST_DELAY)

    # Direct HTML fallback for category subs.
    if config.get("categories"):
        for url in (f"https://www.reddit.com/r/{subreddit}/", f"https://old.reddit.com/r/{subreddit}/"):
            posts.extend(try_source(
                f"html:{url}",
                source_status,
                lambda url=url: fetch_html(url, subreddit, "html", 30),
            ))
            if posts:
                break
            time.sleep(REQUEST_DELAY)

    # Reddit JSON last, because it is commonly blocked on hosted runners.
    if config.get("categories"):
        for category in config.get("categories", []):
            for host in ("old.reddit.com", "www.reddit.com"):
                url = f"https://{host}/r/{subreddit}/{category}.json?limit=50&raw_json=1"
                posts.extend(try_source(
                    f"json:{host}:r/{subreddit}:{category}",
                    source_status,
                    lambda url=url, category=category: fetch_reddit_json(url, subreddit, category, 40),
                ))
                if posts:
                    break
            if posts:
                break
            time.sleep(REQUEST_DELAY)

    unique = deduplicate(posts)
    print(f"  → r/{subreddit}: {len(unique)} unique posts collected")
    return unique


def fetch_current_roster() -> Dict[str, str]:
    roster = dict(FALLBACK_PLAYERS)
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{TEAM_ID_ESPN}?enable=roster"
    try:
        data = json.loads(request_text(url, accept="application/json,*/*"))
        athletes = data.get("team", {}).get("athletes", []) or data.get("athletes", [])
        for item in athletes:
            name = clean_text(item.get("displayName") or item.get("fullName"), 80)
            if " " in name:
                last = name.split()[-1].lower().replace(".", "")
                if len(last) >= 4:
                    roster[last] = name
        print(f"Roster loaded: {len(roster)} keys")
    except Exception as exc:
        print(f"Roster fetch skipped/failed; fallback roster used: {str(exc)[:120]}")
    return roster


def score_post_text(text: str) -> int:
    lowered = f" {text.lower()} "
    score = 0
    for word in STRONG_POSITIVE:
        if word in lowered:
            score += 3
    for word in POSITIVE:
        if word in lowered:
            score += 1
    for word in NEGATIVE:
        if word in lowered:
            score -= 1
    for word in STRONG_NEGATIVE:
        if word in lowered:
            score -= 3
    if " fire " in lowered and not re.search(r"fire\s+(the\s+)?(coach|gm|coordinator|quinn|peters|staff)", lowered):
        score += 1
    if re.search(r"fire\s+(the\s+)?(coach|gm|coordinator|quinn|peters|staff)", lowered):
        score -= 3
    return score


def analyze_sentiment(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not posts:
        return {"score": 0, "label": "No data", "posts_analyzed": 0, "highlights_positive": [], "highlights_negative": []}
    total_score = 0.0
    total_weight = 0.0
    positive = []
    negative = []
    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        ps = score_post_text(text)
        engagement = max(1.0, (abs(safe_int(post.get("score"))) + safe_int(post.get("comments")) + 1) ** 0.5)
        total_score += ps * engagement
        total_weight += engagement
        item = {"title": post.get("title", "")[:140], "score": post.get("score", 0), "comments": post.get("comments", 0), "url": post.get("url", "")}
        if ps >= 2:
            positive.append(item)
        if ps <= -2:
            negative.append(item)
    raw = total_score / max(0.01, total_weight) * 10
    score = max(-100, min(100, round(raw)))
    if score >= 50:
        label = "EXTREMELY FIRED UP"
    elif score >= 25:
        label = "OPTIMISTIC"
    elif score >= 10:
        label = "CAUTIOUSLY HOPEFUL"
    elif score >= -10:
        label = "MIXED"
    elif score >= -25:
        label = "CONCERNED"
    elif score >= -50:
        label = "FRUSTRATED"
    else:
        label = "IN SHAMBLES"
    return {"score": score, "label": label, "posts_analyzed": len(posts), "highlights_positive": positive[:5], "highlights_negative": negative[:5]}


def detect_hot_topics(posts: List[Dict[str, Any]], min_posts: int = 1) -> List[Dict[str, Any]]:
    topic_scores: Dict[str, int] = {}
    topic_posts: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                engagement = safe_int(post.get("score")) + safe_int(post.get("comments"))
                topic_scores[topic] = topic_scores.get(topic, 0) + engagement + 10
                topic_posts[topic].append({"title": post.get("title", "")[:140], "score": post.get("score", 0), "comments": post.get("comments", 0), "url": post.get("url", "")})
    hot = []
    for topic, score in sorted(topic_scores.items(), key=lambda item: -item[1]):
        if len(topic_posts[topic]) >= min_posts:
            hot.append({"topic": topic, "buzz_score": score, "post_count": len(topic_posts[topic]), "top_posts": topic_posts[topic][:3]})
    return hot[:8]


def track_player_mentions(posts: List[Dict[str, Any]], roster: Dict[str, str]) -> List[Dict[str, Any]]:
    mentions = defaultdict(lambda: {"count": 0, "sentiment": 0, "posts": []})
    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        lowered = text.lower()
        post_score = score_post_text(text)
        for key, full_name in roster.items():
            if re.search(rf"\b{re.escape(key.lower())}\b", lowered) or full_name.lower() in lowered:
                item = mentions[full_name]
                item["count"] += 1
                item["sentiment"] += post_score
                if len(item["posts"]) < 3:
                    item["posts"].append({"title": post.get("title", "")[:140], "score": post.get("score", 0), "url": post.get("url", "")})
    result = []
    for full_name, data in sorted(mentions.items(), key=lambda item: -item[1]["count"]):
        avg_sentiment = round(data["sentiment"] / max(1, data["count"]) * 10)
        result.append({"player": full_name, "mentions": data["count"], "sentiment": max(-100, min(100, avg_sentiment)), "top_posts": data["posts"]})
    return result[:20]


def generate_pulse_summary(sentiment: Dict[str, Any], hot_topics: List[Dict[str, Any]], player_mentions: List[Dict[str, Any]]) -> str:
    score = sentiment.get("score", 0)
    top_topic = hot_topics[0]["topic"] if hot_topics else "the team"
    top_player = player_mentions[0]["player"] if player_mentions else None
    if score >= 40:
        summary = f"The fan base is buzzing, with {top_topic} driving the conversation."
    elif score >= 15:
        summary = f"The mood is leaning positive around {top_topic}."
    elif score >= -15:
        summary = f"Fan conversation is mixed, with {top_topic} drawing the most debate."
    elif score >= -40:
        summary = f"Fans are restless, and concerns around {top_topic} are showing up."
    else:
        summary = f"Frustration is high, with {top_topic} taking the most heat."
    if top_player:
        summary += f" {top_player.split()[-1]} is one of the loudest player buzz signals."
    return summary


def update_history(output: Dict[str, Any]) -> Dict[str, Any]:
    history = load_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append({
        "updated": output.get("updated"),
        "updated_iso": output.get("updated_iso"),
        "score": output.get("pulse", {}).get("score"),
        "label": output.get("pulse", {}).get("label"),
        "posts_collected": output.get("posts_collected"),
        "top_topic": output.get("hot_topics", [{}])[0].get("topic") if output.get("hot_topics") else None,
    })
    history = history[-60:]
    write_json(HISTORY_PATH, history)
    output["history"] = history[-14:]
    return output


def base_payload(posts: List[Dict[str, Any]], source_status: Dict[str, Any], stale: bool) -> Dict[str, Any]:
    now = time.time()
    sentiment = analyze_sentiment(posts)
    hot_topics = detect_hot_topics(posts)
    roster = fetch_current_roster()
    player_mentions = track_player_mentions(posts, roster)
    previous = load_json(OUTPUT_PATH, {})
    previous_score = previous.get("pulse", {}).get("score") if isinstance(previous, dict) else None
    score = sentiment["score"]
    score_delta = score - previous_score if isinstance(previous_score, int) and posts else None
    summary = generate_pulse_summary(sentiment, hot_topics, player_mentions) if posts else "No live posts were collected. Check meta.source_status in this file or the GitHub Action log."
    output = {
        "team": "WAS",
        "team_name": "Washington Commanders",
        "source_label": "Community Pulse",
        "updated": now if posts else previous.get("updated") if isinstance(previous, dict) else None,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)) if posts else previous.get("updated_iso") if isinstance(previous, dict) else None,
        "last_attempted_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "posts_collected": len(posts),
        "pulse": {
            "score": score,
            "label": sentiment["label"],
            "summary": summary,
            "posts_analyzed": sentiment["posts_analyzed"],
            "previous_score": previous_score,
            "score_delta": score_delta,
            "stale": bool(stale),
            "stale_after_hours": STALE_AFTER_HOURS,
        },
        "sentiment": sentiment,
        "hot_topics": hot_topics,
        "player_mentions": player_mentions,
        "highlights": {"positive": sentiment["highlights_positive"], "negative": sentiment["highlights_negative"]},
        "recent_posts": sorted(posts, key=lambda item: -safe_float(item.get("created")))[:60],
        "errors": {} if posts else {"fatal": "No posts collected from PullPush, Reddit RSS, Reddit JSON, or Reddit HTML."},
        "meta": {
            "privacy_note": "Only public post metadata/titles and derived buzz scores are saved. Usernames and long selftext are intentionally omitted.",
            "manual_fallback_available": True,
            "signal_note": "This is a fan conversation signal, not an official team report or factual player evaluation.",
            "source_strategy": "PullPush first, old.reddit RSS second, reddit.com RSS/JSON/HTML fallback, no API key.",
            "source_status": source_status,
        },
    }
    if posts:
        output = update_history(output)
    return output


def main() -> int:
    print("=" * 72)
    print("COMMANDERS PULSE BUILDER — PULLPUSH + REDDIT FALLBACKS")
    print("=" * 72)
    source_status: Dict[str, Any] = {"attempts": []}
    all_posts: List[Dict[str, Any]] = []
    for config in SUBS_TO_SCAN:
        all_posts.extend(collect_for_config(config, source_status))
    all_posts = deduplicate(all_posts)
    print(f"\nTotal unique posts collected: {len(all_posts)}")
    output = base_payload(all_posts, source_status, stale=not bool(all_posts))
    write_json(OUTPUT_PATH, output)
    print(f"Wrote {OUTPUT_PATH}")
    print("posts_collected:", output.get("posts_collected"))
    print("pulse:", json.dumps(output.get("pulse"), indent=2))
    if not all_posts:
        print("SOURCE DEBUG:")
        print(json.dumps(source_status, indent=2)[:12000])
        # Do not fail the Action here. We still want the diagnostic JSON committed.
        return 0
    if output.get("hot_topics"):
        print("top_topic:", output["hot_topics"][0].get("topic"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
