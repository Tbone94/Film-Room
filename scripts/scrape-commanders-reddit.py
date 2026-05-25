#!/usr/bin/env python3
"""
Commanders Pulse Builder

Builds data/reddit-pulse.json from public community discussion signals.
Designed to run in GitHub Actions. No Reddit account, OAuth token, API key,
or pip dependency is required.

v1.2 reliability notes:
- Uses Reddit RSS feeds first because GitHub/Netlify environments often get
  blocked or throttled by Reddit's public JSON endpoints.
- Falls back to Reddit JSON endpoints if RSS is unavailable.
- Writes clear source/debug errors into data/reddit-pulse.json when collection
  fails, so the next failure is diagnosable from the file itself.
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
DELAY_BETWEEN_REQUESTS = 1.2
SELFTEXT_MAX = 280
STALE_AFTER_HOURS = 72

# A browser-like UA is more reliable for public RSS/JSON reads from GitHub Actions.
REDDIT_USER_AGENT = (
    "Mozilla/5.0 (compatible; CommandersPulse/1.2; "
    "+https://github.com/tgiamberini95/commanders-pulse)"
)

SUBS_TO_SCAN = [
    {
        "key": "commanders",
        "subreddit": "Commanders",
        "fetch_categories": ["hot", "new", "top"],
        "fetch_limit": 35,
        "search_queries": [
            "Jayden Daniels",
            "Commanders draft",
            "Commanders offense",
            "Commanders defense",
            "Commanders trade free agent",
            "Commanders injury camp OTA minicamp",
        ],
        "search_limit": 15,
    },
    {
        "key": "nfl_commanders",
        "subreddit": "nfl",
        "fetch_categories": [],
        "fetch_limit": 0,
        "search_queries": ["Commanders", "Washington Commanders", "Jayden Daniels"],
        "search_limit": 20,
    },
    {
        "key": "fantasy_commanders",
        "subreddit": "fantasyfootball",
        "fetch_categories": [],
        "fetch_limit": 0,
        "search_queries": [
            "Jayden Daniels fantasy",
            "Commanders fantasy",
            "McLaurin fantasy",
            "Ekeler Robinson fantasy",
        ],
        "search_limit": 12,
    },
]

STRONG_POSITIVE = [
    "elite", "beast", "monster", "stud", "generational", "franchise", "pro bowl",
    "all pro", "dominant", "unstoppable", "clutch", "goat", "mvp", "breakout",
    "lethal", "electric", "special", "game changer", "locked in", "baller",
    "built different", "league winner", "super bowl", "playoff", "contender",
]
POSITIVE = [
    "good", "great", "solid", "improving", "better", "growth", "excited", "healthy",
    "confident", "impressed", "athletic", "fast", "strong", "win", "winning", "hope",
    "optimistic", "love", "hype", "hyped", "chemistry", "development", "potential",
    "underrated", "upgrade", "improved", "depth", "talent", "promising", "bright future",
    "looks sharp", "steal", "value", "ceiling",
]
NEGATIVE = [
    "bad", "concern", "worried", "disappointing", "slow", "injury", "risky", "overrated",
    "overpay", "limited", "decline", "regression", "aging", "old", "washed", "backup",
    "benched", "frustrating", "inconsistent", "weak", "liability", "problem", "issue",
    "miss", "lose", "losing", "struggling", "questionable", "doubt", "cooked",
]
STRONG_NEGATIVE = [
    "bust", "trash", "terrible", "awful", "disaster", "fraud", "done", "finished",
    "washed up", "waste", "nightmare", "toxic", "cut him", "release him", "tank",
    "tanking", "dumpster fire", "trainwreck", "embarrassing", "pathetic", "worst",
    "horrible", "garbage",
]

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

FALLBACK_PLAYERS = {
    "daniels": "Jayden Daniels",
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


def clean_text(value: Any, max_len: int = 240) -> str:
    text = html.unescape(str(value or "")).replace("\n", " ").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def wordish_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:100]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
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
            "User-Agent": REDDIT_USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_current_roster() -> Dict[str, str]:
    """Fetch current Commanders roster from ESPN public endpoint. Falls back safely."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{TEAM_ID_ESPN}?enable=roster"
    roster = dict(FALLBACK_PLAYERS)
    try:
        text = request_text(url, accept="application/json")
        data = json.loads(text)
        athletes = data.get("team", {}).get("athletes", []) or data.get("athletes", [])
        for item in athletes:
            name = clean_text(item.get("displayName") or item.get("fullName"), 80)
            if not name or " " not in name:
                continue
            last = name.split()[-1].lower().replace(".", "")
            if len(last) >= 4:
                roster[last] = name
        print(f"Roster loaded: {len(roster)} player/name keys")
    except Exception as exc:
        print(f"Roster fetch failed; using fallback roster: {str(exc)[:120]}")
    return roster


def normalize_post(post: Any) -> Optional[Dict[str, Any]]:
    if not post or not isinstance(post, dict):
        return None
    title = clean_text(post.get("title"), 220)
    if not title:
        return None

    permalink = post.get("permalink", "") or ""
    url = post.get("url", "") or ""
    if permalink and not str(permalink).startswith("http"):
        permalink = f"https://reddit.com{permalink}"

    return {
        "title": title,
        "selftext": clean_text(post.get("selftext") or post.get("body") or post.get("summary"), SELFTEXT_MAX),
        "score": safe_int(post.get("score")),
        "comments": safe_int(post.get("num_comments") or post.get("comments")),
        "created": safe_float(post.get("created_utc") or post.get("created")),
        "url": permalink or url,
        "subreddit": clean_text(post.get("subreddit"), 60),
        "flair": clean_text(post.get("link_flair_text") or post.get("flair"), 80),
    }


def deduplicate(posts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for post in posts:
        key = wordish_key(post.get("title", ""))
        if key and key not in seen:
            seen.add(key)
            unique.append(post)
    return unique


def rss_time_to_epoch(value: str) -> float:
    if not value:
        return 0.0
    try:
        dt = email.utils.parsedate_to_datetime(value)
        return dt.timestamp()
    except Exception:
        try:
            cleaned = value.replace("Z", "+00:00")
            from datetime import datetime
            return datetime.fromisoformat(cleaned).timestamp()
        except Exception:
            return 0.0


def strip_reddit_title_prefix(title: str) -> str:
    # Reddit search feeds sometimes prepend subreddit/user context. Keep this conservative.
    return clean_text(title.replace(" - Reddit", ""), 220)


def parse_reddit_rss(xml_text: str, subreddit: str, source_category: str) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    root = ET.fromstring(xml_text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
    }

    # Reddit .rss currently uses Atom entries.
    entries = root.findall("atom:entry", ns)
    if not entries:
        entries = root.findall(".//entry")

    for entry in entries:
        def find_text(*names: str) -> str:
            for name in names:
                node = entry.find(name, ns) if ":" in name else entry.find(name)
                if node is not None and node.text:
                    return node.text
            return ""

        title = strip_reddit_title_prefix(find_text("atom:title", "title"))
        summary = clean_text(find_text("atom:content", "atom:summary", "summary", "description"), SELFTEXT_MAX)
        link = ""
        for link_node in entry.findall("atom:link", ns) + entry.findall("link"):
            href = link_node.attrib.get("href")
            rel = link_node.attrib.get("rel", "alternate")
            if href and rel in ("alternate", ""):
                link = href
                break
        if not link:
            link = find_text("atom:id", "id")
        created = rss_time_to_epoch(find_text("atom:updated", "atom:published", "updated", "pubDate"))
        normalized = normalize_post({
            "title": title,
            "selftext": summary,
            "score": 0,
            "comments": 0,
            "created_utc": created,
            "url": link,
            "subreddit": subreddit,
            "flair": "",
        })
        if normalized:
            normalized["source_category"] = source_category
            normalized["source_type"] = "rss"
            posts.append(normalized)
    return posts


def children_to_posts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    children = payload.get("data", {}).get("children", [])
    posts = []
    for child in children:
        if isinstance(child, dict) and isinstance(child.get("data"), dict):
            posts.append(child["data"])
    return posts


def fetch_json_posts(url: str) -> List[Dict[str, Any]]:
    text = request_text(url, accept="application/json,text/plain,*/*")
    return children_to_posts(json.loads(text))


def reddit_rss_urls_for_category(subreddit: str, category: str, limit: int) -> List[str]:
    category = category.lower().strip()
    if category == "hot":
        paths = [".rss", "hot/.rss"]
    elif category == "new":
        paths = ["new/.rss"]
    elif category == "top":
        paths = ["top/.rss?t=week"]
    else:
        paths = [f"{category}/.rss"]
    return [f"https://www.reddit.com/r/{subreddit}/{path}" for path in paths]


def reddit_json_urls_for_category(subreddit: str, category: str, limit: int) -> List[str]:
    category = category.lower().strip()
    time_query = "&t=week" if category == "top" else ""
    return [
        f"https://www.reddit.com/r/{subreddit}/{category}.json?limit={int(limit)}{time_query}",
        f"https://old.reddit.com/r/{subreddit}/{category}.json?limit={int(limit)}{time_query}",
    ]


def reddit_rss_urls_for_search(subreddit: str, query: str, limit: int) -> List[str]:
    encoded = urllib.parse.quote_plus(query)
    return [
        f"https://www.reddit.com/r/{subreddit}/search.rss?q={encoded}&restrict_sr=on&sort=relevance&t=week&limit={int(limit)}",
        f"https://old.reddit.com/r/{subreddit}/search.rss?q={encoded}&restrict_sr=on&sort=relevance&t=week&limit={int(limit)}",
    ]


def reddit_json_urls_for_search(subreddit: str, query: str, limit: int) -> List[str]:
    encoded = urllib.parse.quote_plus(query)
    return [
        f"https://www.reddit.com/r/{subreddit}/search.json?q={encoded}&restrict_sr=1&sort=relevance&t=week&limit={int(limit)}",
        f"https://old.reddit.com/r/{subreddit}/search.json?q={encoded}&restrict_sr=1&sort=relevance&t=week&limit={int(limit)}",
    ]


def fetch_from_many(urls: List[str], subreddit: str, source_category: str, limit: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    for url in urls:
        try:
            if url.endswith(".rss") or ".rss?" in url or "/.rss" in url:
                text = request_text(url, accept="application/atom+xml,application/rss+xml,text/xml,*/*")
                posts = parse_reddit_rss(text, subreddit, source_category)
            else:
                posts = []
                for item in fetch_json_posts(url):
                    normalized = normalize_post(item)
                    if normalized:
                        normalized["source_category"] = source_category
                        normalized["source_type"] = "json"
                        posts.append(normalized)
            if posts:
                return posts[:limit], errors
            errors.append(f"0 posts from {url}")
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code} from {url}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:120]} from {url}")
        time.sleep(DELAY_BETWEEN_REQUESTS)
    return [], errors


def fetch_subreddit_category(subreddit: str, category: str, limit: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    rss_urls = reddit_rss_urls_for_category(subreddit, category, limit)
    json_urls = reddit_json_urls_for_category(subreddit, category, limit)
    return fetch_from_many(rss_urls + json_urls, subreddit, category, limit)


def search_subreddit(subreddit: str, query: str, limit: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    rss_urls = reddit_rss_urls_for_search(subreddit, query, limit)
    json_urls = reddit_json_urls_for_search(subreddit, query, limit)
    return fetch_from_many(rss_urls + json_urls, subreddit, f"search:{query}", limit)


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
    if " not bad " in lowered:
        score += 1
    if " not good " in lowered:
        score -= 1
    return score


def analyze_sentiment(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not posts:
        return {"score": 0, "label": "No data", "posts_analyzed": 0, "highlights_positive": [], "highlights_negative": []}

    total_score = 0.0
    total_weight = 0.0
    highlights_pos = []
    highlights_neg = []

    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        ps = score_post_text(text)
        engagement = max(1.0, (abs(post.get("score", 0)) + post.get("comments", 0) + 1) ** 0.5)
        total_score += ps * engagement
        total_weight += engagement

        highlight = {"title": post.get("title", "")[:140], "score": post.get("score", 0), "comments": post.get("comments", 0), "url": post.get("url", "")}
        if ps >= 2:
            highlights_pos.append(highlight)
        if ps <= -2:
            highlights_neg.append(highlight)

    raw = total_score / max(0.01, total_weight) * 10
    clamped = max(-100, min(100, round(raw)))
    if clamped >= 50:
        label = "EXTREMELY FIRED UP"
    elif clamped >= 25:
        label = "OPTIMISTIC"
    elif clamped >= 10:
        label = "CAUTIOUSLY HOPEFUL"
    elif clamped >= -10:
        label = "MIXED"
    elif clamped >= -25:
        label = "CONCERNED"
    elif clamped >= -50:
        label = "FRUSTRATED"
    else:
        label = "IN SHAMBLES"

    return {
        "score": clamped,
        "label": label,
        "posts_analyzed": len(posts),
        "highlights_positive": highlights_pos[:5],
        "highlights_negative": highlights_neg[:5],
    }


def detect_hot_topics(posts: List[Dict[str, Any]], min_posts: int = 1) -> List[Dict[str, Any]]:
    topic_scores: Dict[str, int] = {}
    topic_posts: Dict[str, list] = defaultdict(list)
    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                engagement = safe_int(post.get("score")) + safe_int(post.get("comments"))
                topic_scores[topic] = topic_scores.get(topic, 0) + engagement + 10
                topic_posts[topic].append({"title": post.get("title", "")[:140], "score": post.get("score", 0), "comments": post.get("comments", 0), "url": post.get("url", "")})
    hot = []
    for topic, score in sorted(topic_scores.items(), key=lambda item: -item[1]):
        posts_for_topic = topic_posts[topic]
        if len(posts_for_topic) >= min_posts:
            hot.append({"topic": topic, "buzz_score": score, "post_count": len(posts_for_topic), "top_posts": posts_for_topic[:3]})
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


def scrape_subreddit(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    posts: List[Dict[str, Any]] = []
    errors: List[str] = []
    for category in config.get("fetch_categories", []):
        raw, fetch_errors = fetch_subreddit_category(config["subreddit"], category, config.get("fetch_limit", 25))
        errors.extend([f"{category}: {err}" for err in fetch_errors])
        posts.extend(raw)
        print(f"    {category}: {len(raw or [])} posts")
        time.sleep(DELAY_BETWEEN_REQUESTS)
    for query in config.get("search_queries", []):
        raw, fetch_errors = search_subreddit(config["subreddit"], query, config.get("search_limit", 10))
        errors.extend([f"search '{query}': {err}" for err in fetch_errors])
        posts.extend(raw)
        print(f"    search '{query}': {len(raw or [])} posts")
        time.sleep(DELAY_BETWEEN_REQUESTS)
    return deduplicate(posts), errors[:30]


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


def build_failure_output(errors: Dict[str, Any]) -> Dict[str, Any]:
    previous = load_json(OUTPUT_PATH, {})
    now = time.time()
    previous_pulse = previous.get("pulse", {}) if isinstance(previous, dict) else {}
    return {
        "team": "WAS",
        "team_name": "Washington Commanders",
        "source_label": "Community Pulse",
        "updated": previous.get("updated") if isinstance(previous, dict) else None,
        "updated_iso": previous.get("updated_iso") if isinstance(previous, dict) else None,
        "last_attempted_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "posts_collected": previous.get("posts_collected", 0) if isinstance(previous, dict) else 0,
        "pulse": {
            **previous_pulse,
            "stale": True,
            "summary": previous_pulse.get("summary") or "Community Pulse data is temporarily unavailable. Check errors.source_debug in data/reddit-pulse.json.",
            "stale_after_hours": STALE_AFTER_HOURS,
        },
        "sentiment": previous.get("sentiment", {}) if isinstance(previous, dict) else {},
        "hot_topics": previous.get("hot_topics", []) if isinstance(previous, dict) else [],
        "player_mentions": previous.get("player_mentions", []) if isinstance(previous, dict) else [],
        "highlights": previous.get("highlights", {"positive": [], "negative": []}) if isinstance(previous, dict) else {"positive": [], "negative": []},
        "recent_posts": previous.get("recent_posts", []) if isinstance(previous, dict) else [],
        "errors": errors,
        "meta": {
            "privacy_note": "Only public post metadata/titles and derived buzz scores are saved. Usernames and long selftext are intentionally omitted.",
            "manual_fallback_available": True,
            "debug_note": "RSS is tried first, Reddit JSON second. HTTP 403/429 means Reddit is blocking that runner/request.",
        },
    }


def main() -> None:
    print("=" * 64)
    print("COMMANDERS PULSE BUILDER — RSS-FIRST")
    print("=" * 64)
    previous = load_json(OUTPUT_PATH, {})
    previous_score = previous.get("pulse", {}).get("score") if isinstance(previous, dict) else None
    roster = fetch_current_roster()
    all_posts: List[Dict[str, Any]] = []
    all_errors: Dict[str, Any] = {}

    for config in SUBS_TO_SCAN:
        print(f"\nScanning r/{config['subreddit']} ({config['key']})...")
        posts, errors = scrape_subreddit(config)
        all_posts.extend(posts)
        if errors:
            all_errors[config["key"]] = errors
        print(f"  → {len(posts)} posts collected")

    all_posts = deduplicate(all_posts)
    print(f"\nTotal unique posts: {len(all_posts)}")

    if not all_posts:
        output = build_failure_output({**all_errors, "fatal": "No posts collected", "last_attempted_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        write_json(OUTPUT_PATH, output)
        print(f"No posts collected. Wrote fallback output to {OUTPUT_PATH}")
        return

    sentiment = analyze_sentiment(all_posts)
    hot_topics = detect_hot_topics(all_posts)
    player_mentions = track_player_mentions(all_posts, roster)
    summary = generate_pulse_summary(sentiment, hot_topics, player_mentions)

    now = time.time()
    score = sentiment["score"]
    score_delta = score - previous_score if isinstance(previous_score, int) else None

    output = {
        "team": "WAS",
        "team_name": "Washington Commanders",
        "source_label": "Community Pulse",
        "updated": now,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "last_attempted_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "posts_collected": len(all_posts),
        "pulse": {
            "score": score,
            "label": sentiment["label"],
            "summary": summary,
            "posts_analyzed": sentiment["posts_analyzed"],
            "previous_score": previous_score,
            "score_delta": score_delta,
            "stale": False,
            "stale_after_hours": STALE_AFTER_HOURS,
        },
        "sentiment": sentiment,
        "hot_topics": hot_topics,
        "player_mentions": player_mentions,
        "highlights": {"positive": sentiment["highlights_positive"], "negative": sentiment["highlights_negative"]},
        "recent_posts": sorted(all_posts, key=lambda item: -safe_float(item.get("created")))[:50],
        "errors": all_errors,
        "meta": {
            "privacy_note": "Only public post metadata/titles and derived buzz scores are saved. Usernames and long selftext are intentionally omitted.",
            "manual_fallback_available": True,
            "signal_note": "This is a fan conversation signal, not an official team report or factual player evaluation.",
            "source_strategy": "Reddit RSS first, Reddit JSON fallback, no API key.",
        },
    }
    output = update_history(output)
    write_json(OUTPUT_PATH, output)

    print(f"\nDone. Wrote {OUTPUT_PATH}")
    print(f"Pulse: {score:+d} — {sentiment['label']}")
    if score_delta is not None:
        print(f"Change since last scrape: {score_delta:+d}")
    if hot_topics:
        print(f"Top topic: {hot_topics[0]['topic']} ({hot_topics[0]['post_count']} posts)")
    if player_mentions:
        print(f"Most discussed: {player_mentions[0]['player']} ({player_mentions[0]['mentions']} mentions)")


if __name__ == "__main__":
    main()
